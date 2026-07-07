package api

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"pea-api-intellisense/apps/api-go/internal/sendcontrol"
	"pea-api-intellisense/apps/api-go/internal/storage"
)

const (
	APIVersion             = "v1"
	SchemaVersion          = "2026-06-20"
	Mode                   = "shadow"
	ProductionSend         = "blocked"
	inboundPath            = "/api/v1/ais/outage-verifications"
	maxBodyBytes     int64 = 1_000_000
)

var safeID = regexp.MustCompile(`^[A-Za-z0-9_.:@-]+$`)

type ServerConfig struct {
	APIKey             string
	RateLimitPerMinute int
	AllowedOrigin      string
	ProductionSendMode string
	CallbackTransport  string
	EmergencyOff        bool
	Logger             *slog.Logger
}

type Server struct {
	cfg     ServerConfig
	store   storage.Store
	limiter *rateLimiter
}

func NewServer(cfg ServerConfig, store storage.Store) http.Handler {
	if cfg.Logger == nil {
		cfg.Logger = slog.Default()
	}
	if cfg.RateLimitPerMinute < 0 {
		cfg.RateLimitPerMinute = 0
	}
	return &Server{
		cfg:     cfg,
		store:   store,
		limiter: newRateLimiter(cfg.RateLimitPerMinute),
	}
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if s.cfg.AllowedOrigin != "" {
		w.Header().Set("Access-Control-Allow-Origin", s.cfg.AllowedOrigin)
		w.Header().Set("Vary", "Origin")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, X-API-Key, Authorization")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
	}
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	switch {
	case r.URL.Path == "/health" && r.Method == http.MethodGet:
		s.handleHealth(w, r)
	case r.URL.Path == "/metrics" && r.Method == http.MethodGet:
		s.handleMetrics(w, r)
	case r.URL.Path == inboundPath && r.Method == http.MethodGet:
		s.handleContract(w, r)
	case r.URL.Path == inboundPath && r.Method == http.MethodPost:
		s.handlePost(w, r)
	case strings.HasPrefix(r.URL.Path, inboundPath+"/") && r.Method == http.MethodGet:
		s.handleStatus(w, r)
	default:
		writeJSON(w, http.StatusNotFound, errorPayload("NOT_FOUND", "Unknown endpoint", ""))
	}
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	dbStatus := "ok"
	if err := s.store.Health(r.Context()); err != nil {
		dbStatus = "error"
		s.cfg.Logger.Warn("health database check failed", "error", err)
	}
	statusCode := http.StatusOK
	if dbStatus != "ok" {
		statusCode = http.StatusServiceUnavailable
	}
	writeJSON(w, statusCode, map[string]any{
		"api_version":     APIVersion,
		"schema_version":  SchemaVersion,
		"service":         "pea-api-intellisense-go",
		"status":          dbStatus,
		"mode":            Mode,
		"production_send": ProductionSend,
		"send_control":    s.safeSendControlPayload(),
		"database":        dbStatus,
		"generated_at":    nowISO(),
	})
}

func (s *Server) handleContract(w http.ResponseWriter, r *http.Request) {
	if r.URL.Query().Get("view") == "operator" {
		if !s.authorized(r) {
			writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
			return
		}
		limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
		rows, err := s.store.ListStatuses(r.Context(), limit)
		if err != nil {
			s.cfg.Logger.Error("operator list failed", "error", err)
			writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load operator request list", ""))
			return
		}
		items := make([]map[string]any, 0, len(rows))
		for index := range rows {
			row := rows[index]
			items = append(items, statusPayload(&row))
		}
		writeJSON(w, http.StatusOK, map[string]any{
			"api_version":     APIVersion,
			"schema_version":  SchemaVersion,
			"mode":            Mode,
			"production_send": ProductionSend,
			"count":           len(items),
			"items":           items,
			"generated_at":    nowISO(),
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"api_version":     APIVersion,
		"schema_version":  SchemaVersion,
		"mode":            Mode,
		"method":          "POST",
		"path":            inboundPath,
		"status_lookup":   inboundPath + "/{request_id}",
		"production_send": ProductionSend,
	})
}

func (s *Server) handleMetrics(w http.ResponseWriter, r *http.Request) {
	if !s.authorized(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	snapshot, err := s.store.Metrics(r.Context())
	if err != nil {
		s.cfg.Logger.Error("metrics snapshot failed", "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load metrics snapshot", ""))
		return
	}
	payload := map[string]any{
		"api_version":           APIVersion,
		"schema_version":        SchemaVersion,
		"service":               "pea-api-intellisense-go",
		"mode":                  Mode,
		"production_send":       ProductionSend,
		"total_requests":        snapshot.TotalRequests,
		"duplicate_callbacks":   snapshot.DuplicateCallbacks,
		"pending_worker_traces": snapshot.PendingWorkerTraces,
		"not_ready_etr":         snapshot.NotReadyETR,
		"callback_counts":       snapshot.CallbackCounts,
		"outbox_dry_run_held":   snapshot.OutboxDryRunHeld,
		"dead_letters":          snapshot.DeadLetters,
		"truth_observations":    snapshot.TruthObservations,
		"truth_review_needed":   snapshot.TruthReviewNeeded,
		"truth_outage_events":   snapshot.TruthOutageEvents,
		"truth_restore_events":  snapshot.TruthRestoreEvents,
		"truth_open_intervals":  snapshot.TruthOpenIntervals,
		"truth_closed_intervals": snapshot.TruthClosedIntervals,
		"send_control":          s.safeSendControlPayload(),
		"generated_at":          nowISO(),
	}
	if snapshot.LatestReceivedAt != nil {
		payload["latest_received_at"] = snapshot.LatestReceivedAt.Format(time.RFC3339)
	}
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) handlePost(w http.ResponseWriter, r *http.Request) {
	if !s.authorized(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	if ok, retryAfter := s.limiter.allow(clientIP(r)); !ok {
		w.Header().Set("Retry-After", strconv.Itoa(retryAfter))
		writeJSON(w, http.StatusTooManyRequests, errorPayload("RATE_LIMITED", "Too many requests. Retry later.", ""))
		return
	}
	if !strings.Contains(strings.ToLower(r.Header.Get("Content-Type")), "application/json") {
		writeJSON(w, http.StatusUnsupportedMediaType, errorPayload("UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json", ""))
		return
	}
	defer r.Body.Close()
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, maxBodyBytes))
	if err != nil {
		writeJSON(w, http.StatusRequestEntityTooLarge, errorPayload("BODY_TOO_LARGE", "Request body exceeds 1MB pilot limit", ""))
		return
	}
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_JSON", "Request body must be valid JSON", ""))
		return
	}
	req, err := normalizePayload(payload)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_REQUEST", err.Error(), firstText(payload, "request_id", "requestId")))
		return
	}
	s.cfg.Logger.Info("ais inbound request received", "request_id", req.RequestID, "meter_last4", last4(req.MeterNo), "mode", Mode, "production_send", ProductionSend)

	receivedAt := time.Now().UTC()
	callbackStatus := "CAPTURED_NO_CALLBACK_URL"
	accepted := acceptedResponse(req.RequestID, false, callbackStatus, receivedAt)
	callbackPayload := shadowCallbackPayload(req, "NO_PEA_EVIDENCE_FOUND", "LOW", "cloud_shadow_no_worker_result")
	records, err := s.buildStorageRecords(req, accepted, callbackPayload, callbackStatus, receivedAt)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not build safe storage records", req.RequestID))
		return
	}
	duplicate, err := s.store.InsertInbound(r.Context(), records.request, records.truth, records.callback, records.evidence, records.etr, records.send, records.outbox)
	if err != nil {
		s.cfg.Logger.Error("insert inbound failed", "request_id", req.RequestID, "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not persist request", req.RequestID))
		return
	}
	if duplicate {
		s.cfg.Logger.Info("ais inbound duplicate skipped", "request_id", req.RequestID, "mode", Mode, "production_send", ProductionSend)
		callbackStatus = "SKIPPED_DUPLICATE"
		accepted = acceptedResponse(req.RequestID, true, callbackStatus, time.Now().UTC())
		duplicatePayload := duplicateCallbackPayload(req)
		callbackRecord := storage.Callback{
			RequestID:   req.RequestID,
			Mode:        Mode,
			PayloadJSON: mustJSON(duplicatePayload),
			Status:      callbackStatus,
			SentAt:      time.Now().UTC(),
		}
		if err := s.store.InsertCallback(r.Context(), callbackRecord); err != nil {
			s.cfg.Logger.Warn("duplicate callback persist failed", "request_id", req.RequestID, "error", err)
		}
	}
	w.Header().Set("X-Request-ID", req.RequestID)
	w.Header().Set("X-Correlation-ID", correlationID(r, req.RequestID))
	writeJSON(w, http.StatusAccepted, accepted)
}

func (s *Server) handleStatus(w http.ResponseWriter, r *http.Request) {
	if !s.authorized(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	id, err := url.PathUnescape(strings.TrimPrefix(r.URL.Path, inboundPath+"/"))
	if err != nil || id == "" || strings.Contains(id, "/") {
		writeJSON(w, http.StatusNotFound, errorPayload("REQUEST_NOT_FOUND", "No AIS inbound request was found for this request_id", id))
		return
	}
	row, err := s.store.GetStatus(r.Context(), id)
	if errors.Is(err, storage.ErrNotFound) {
		writeJSON(w, http.StatusNotFound, errorPayload("REQUEST_NOT_FOUND", "No AIS inbound request was found for this request_id", id))
		return
	}
	if err != nil {
		s.cfg.Logger.Error("status lookup failed", "request_id", id, "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load request status", id))
		return
	}
	w.Header().Set("X-Request-ID", id)
	w.Header().Set("X-Correlation-ID", correlationID(r, id))
	writeJSON(w, http.StatusOK, statusPayload(row))
}

func (s *Server) authorized(r *http.Request) bool {
	if s.cfg.APIKey == "" {
		return true
	}
	if r.Header.Get("X-API-Key") == s.cfg.APIKey {
		return true
	}
	auth := r.Header.Get("Authorization")
	return strings.HasPrefix(auth, "Bearer ") && strings.TrimPrefix(auth, "Bearer ") == s.cfg.APIKey
}

func (s *Server) sendPolicy() sendcontrol.Policy {
	return sendcontrol.NormalizePolicy(sendcontrol.Policy{
		Mode:              s.cfg.ProductionSendMode,
		EmergencyOff:      s.cfg.EmergencyOff,
		CallbackTransport: s.cfg.CallbackTransport,
		GateVersion:       "blocked_green_gate",
		Source:            "go_api",
	})
}

func (s *Server) safeSendControlPayload() map[string]any {
	policy := s.sendPolicy()
	return map[string]any{
		"mode":               policy.Mode,
		"callback_transport": policy.CallbackTransport,
		"emergency_off":      policy.EmergencyOff,
		"gate_version":       policy.GateVersion,
		"production_send":    ProductionSend,
	}
}

type inboundRequest struct {
	RequestID          string
	MeterNo            string
	SiteID             string
	SourceEventID      string
	EventType          string
	DetectedAt         time.Time
	DetectedAtOriginal string
	OutageAt           *time.Time
	RestoreAt          *time.Time
	TimestampQuality   map[string]any
	TruthValidation    string
	Province           string
	District           string
	Subdistrict        string
	AlarmType          string
	MainCause          string
	Subcause           string
	Raw                map[string]any
}

func normalizePayload(payload map[string]any) (inboundRequest, error) {
	requestID, err := requiredSafeText(payload, "request_id", 128, "request_id", "requestId")
	if err != nil {
		return inboundRequest{}, err
	}
	meter, err := requiredSafeText(payload, "meter_no", 64, "meter_no", "meterNo", "peano", "PEANO")
	if err != nil {
		return inboundRequest{}, err
	}
	siteID, err := optionalBoundedText(payload, "site_id", 128, "site_id", "siteId", "location_id", "locationId", "siteCode", "site_code")
	if err != nil {
		return inboundRequest{}, err
	}
	sourceEventID, err := optionalBoundedText(payload, "source_event_id", 128, "source_event_id", "sourceEventId", "event_id", "eventId", "alarm_id", "alarmId")
	if err != nil {
		return inboundRequest{}, err
	}
	rawTime := firstText(payload, "timestamp", "eventTime", "detected_at", "detectedAt")
	if rawTime == "" {
		return inboundRequest{}, errors.New("timestamp is required")
	}
	detectedAt, quality, err := parseTimestamp(rawTime)
	if err != nil {
		return inboundRequest{}, err
	}
	outageAt, err := parseOptionalTimestamp(payload, "outage_at", "outageAt", "power_outage_at", "powerOutageAt")
	if err != nil {
		return inboundRequest{}, err
	}
	restoreAt, err := parseOptionalTimestamp(payload, "restore_at", "restoreAt", "restored_at", "restoredAt", "power_restore_at", "powerRestoreAt")
	if err != nil {
		return inboundRequest{}, err
	}
	province, err := optionalBoundedText(payload, "province", 120, "province", "provinceName")
	if err != nil {
		return inboundRequest{}, err
	}
	district, err := optionalBoundedText(payload, "district", 120, "district", "districtName", "amphoe", "amphur")
	if err != nil {
		return inboundRequest{}, err
	}
	subdistrict, err := optionalBoundedText(payload, "subdistrict", 120, "subdistrict", "subDistrict", "subdistrictName", "tambon", "tambonName")
	if err != nil {
		return inboundRequest{}, err
	}
	alarmType, err := optionalBoundedText(payload, "alarm_type", 240, "alarm_type", "alarmType", "alarm")
	if err != nil {
		return inboundRequest{}, err
	}
	mainCause, err := optionalBoundedText(payload, "main_cause", 240, "main_cause", "mainCause", "maincause", "MAINCAUSE")
	if err != nil {
		return inboundRequest{}, err
	}
	subcause, err := optionalBoundedText(payload, "subcause", 240, "subcause", "subCause", "sub_cause", "subcause2", "subCause2", "SUBCAUSE2")
	if err != nil {
		return inboundRequest{}, err
	}
	eventType := normalizeTruthEventType(payload, alarmType, mainCause, subcause)
	return inboundRequest{
		RequestID:          requestID,
		MeterNo:            meter,
		SiteID:             siteID,
		SourceEventID:      sourceEventID,
		EventType:          eventType,
		DetectedAt:         detectedAt,
		DetectedAtOriginal: rawTime,
		OutageAt:           outageAt,
		RestoreAt:          restoreAt,
		TimestampQuality:   quality,
		TruthValidation:    truthValidationStatus(eventType, outageAt, restoreAt),
		Province:           province,
		District:           district,
		Subdistrict:        subdistrict,
		AlarmType:          alarmType,
		MainCause:          mainCause,
		Subcause:           subcause,
		Raw:                payload,
	}, nil
}

func requiredSafeText(payload map[string]any, field string, max int, keys ...string) (string, error) {
	value := firstText(payload, keys...)
	if value == "" {
		return "", fmt.Errorf("%s is required", field)
	}
	if len(value) > max {
		return "", fmt.Errorf("%s must be %d characters or fewer", field, max)
	}
	if !safeID.MatchString(value) {
		return "", fmt.Errorf("%s may contain only letters, numbers, dash, underscore, dot, colon, or at sign", field)
	}
	return value, nil
}

func optionalBoundedText(payload map[string]any, field string, max int, keys ...string) (string, error) {
	value := firstText(payload, keys...)
	if utf8.RuneCountInString(value) > max {
		return "", fmt.Errorf("%s must be %d characters or fewer", field, max)
	}
	return value, nil
}

func firstText(payload map[string]any, keys ...string) string {
	lower := map[string]any{}
	for key, value := range payload {
		lower[strings.ToLower(key)] = value
	}
	for _, key := range keys {
		value, ok := payload[key]
		if !ok {
			value = lower[strings.ToLower(key)]
		}
		if value == nil {
			continue
		}
		text := strings.TrimSpace(fmt.Sprint(value))
		if text != "" {
			return text
		}
	}
	return ""
}

func parseTimestamp(value string) (time.Time, map[string]any, error) {
	if parsed, err := time.Parse(time.RFC3339, value); err == nil {
		return parsed.UTC(), map[string]any{"status": "OK", "flags": []string{}}, nil
	}
	layouts := []string{"2006-01-02T15:04:05", "2006-01-02 15:04:05"}
	bangkok := time.FixedZone("Asia/Bangkok", 7*60*60)
	for _, layout := range layouts {
		if parsed, err := time.ParseInLocation(layout, value, bangkok); err == nil {
			return parsed.UTC(), map[string]any{"status": "REVIEW", "flags": []string{"timezone_assumed_bangkok"}}, nil
		}
	}
	return time.Time{}, nil, errors.New("timestamp must be ISO 8601, preferably with timezone such as +07:00")
}

func parseOptionalTimestamp(payload map[string]any, keys ...string) (*time.Time, error) {
	raw := firstText(payload, keys...)
	if raw == "" {
		return nil, nil
	}
	parsed, _, err := parseTimestamp(raw)
	if err != nil {
		return nil, fmt.Errorf("%s must be ISO 8601, preferably with timezone such as +07:00", keys[0])
	}
	return &parsed, nil
}

type storageRecords struct {
	request  storage.InboundRequest
	truth    storage.TruthObservation
	callback storage.Callback
	evidence storage.EvidenceTrace
	etr      storage.ETRCandidate
	send     storage.SendDecision
	outbox   storage.CallbackOutbox
}

func (s *Server) buildStorageRecords(req inboundRequest, accepted map[string]any, callbackPayload map[string]any, callbackStatus string, receivedAt time.Time) (storageRecords, error) {
	requestJSON := redactPayload(map[string]any{
		"request_id":             req.RequestID,
		"meter_no":               req.MeterNo,
		"site_id":                req.SiteID,
		"source_event_id":        req.SourceEventID,
		"event_type":             req.EventType,
		"detected_at":            req.DetectedAt.Format(time.RFC3339),
		"detected_at_original":   req.DetectedAtOriginal,
		"outage_at":              formatTimePtr(req.OutageAt),
		"restore_at":             formatTimePtr(req.RestoreAt),
		"timestamp_quality":      req.TimestampQuality,
		"truth_validation":       req.TruthValidation,
		"province":               req.Province,
		"district":               req.District,
		"subdistrict":            req.Subdistrict,
		"alarm_type":             req.AlarmType,
		"main_cause":             req.MainCause,
		"subcause":               req.Subcause,
		"production_send":        ProductionSend,
		"trust_boundary_source":  "AIS",
		"raw_field_names_stored": false,
	})
	evidence := map[string]any{
		"source":          "go_cloud_shadow_api",
		"match_found":     false,
		"match_level":     "",
		"confidence":      "LOW",
		"reason":          "python_worker_pending_or_no_evidence_loaded",
		"production_send": ProductionSend,
	}
	decision := sendcontrol.Evaluate(
		s.sendPolicy(),
		sendcontrol.Candidate{
			EligibilityStatus: "red_blocked",
			GatePassed:        false,
			OwnerApproved:     false,
			CallbackApproved:  false,
		},
	)
	callbackPayload["send_decision"] = map[string]any{
		"policy_mode":        decision.PolicyMode,
		"effective_mode":     decision.EffectiveMode,
		"eligibility_status": decision.EligibilityStatus,
		"decision":           decision.Decision,
		"reason":             decision.Reason,
		"gate_version":       decision.GateVersion,
		"callback_transport": decision.Transport,
		"production_send":    ProductionSend,
	}
	callbackJSON := mustJSON(callbackPayload)
	payloadHash := hashRaw(callbackJSON)
	return storageRecords{
		request: storage.InboundRequest{
			RequestID:          req.RequestID,
			ReceivedAt:         receivedAt,
			MeterHash:          hashMeter(req.MeterNo),
			MeterLast4:         last4(req.MeterNo),
			DetectedAt:         req.DetectedAt,
			DetectedAtOriginal: req.DetectedAtOriginal,
			TimestampQuality:   mustJSON(req.TimestampQuality),
			Province:           req.Province,
			District:           req.District,
			Subdistrict:        req.Subdistrict,
			RequestJSON:        mustJSON(requestJSON),
			ResponseJSON:       mustJSON(accepted),
			CallbackStatus:     callbackStatus,
		},
		truth: storage.TruthObservation{
			RequestID:           req.RequestID,
			Source:              "AIS",
			SourceEventID:       req.SourceEventID,
			SiteHash:            hashOptional(req.SiteID),
			SiteLast4:           last4(req.SiteID),
			MeterHash:           hashMeter(req.MeterNo),
			MeterLast4:          last4(req.MeterNo),
			EventType:           req.EventType,
			DetectedAt:          req.DetectedAt,
			OutageAt:            req.OutageAt,
			RestoreAt:           req.RestoreAt,
			TimestampQuality:    mustJSON(req.TimestampQuality),
			PayloadSummaryJSON:  mustJSON(truthSummaryPayload(req)),
			ValidationStatus:    req.TruthValidation,
			ProductionSend:      ProductionSend,
			CreatedAt:           receivedAt,
		},
		callback: storage.Callback{
			RequestID:   req.RequestID,
			Mode:        Mode,
			PayloadJSON: callbackJSON,
			Status:      callbackStatus,
			SentAt:      receivedAt,
		},
		evidence: storage.EvidenceTrace{
			RequestID:      req.RequestID,
			TraceStatus:    "PENDING_WORKER",
			MatchFound:     false,
			Confidence:     "LOW",
			EvidenceJSON:   mustJSON(evidence),
			ProductionSend: ProductionSend,
			GeneratedAt:    receivedAt,
		},
		etr: storage.ETRCandidate{
			RequestID:      req.RequestID,
			Status:         "NOT_READY_FOR_AUTO_SEND",
			ModelVersion:   "shadow",
			ProductionGate: "blocked_green_gate",
			ProductionSend: ProductionSend,
			GeneratedAt:    receivedAt,
		},
		send: storage.SendDecision{
			RequestID:         req.RequestID,
			PolicyMode:        decision.PolicyMode,
			EffectiveMode:     decision.EffectiveMode,
			EligibilityStatus: decision.EligibilityStatus,
			Decision:          decision.Decision,
			Reason:            decision.Reason,
			GateVersion:       decision.GateVersion,
			Source:            decision.Source,
			ProductionSend:    ProductionSend,
			DecidedAt:         receivedAt,
		},
		outbox: storage.CallbackOutbox{
			RequestID:      req.RequestID,
			PayloadHash:    payloadHash,
			PayloadJSON:    callbackJSON,
			Transport:      decision.Transport,
			Status:         "DRY_RUN_HELD",
			MaxAttempts:    5,
			ProductionSend: ProductionSend,
			CreatedAt:      receivedAt,
			UpdatedAt:      receivedAt,
		},
	}, nil
}

func acceptedResponse(requestID string, duplicate bool, callbackStatus string, receivedAt time.Time) map[string]any {
	return map[string]any{
		"api_version":     APIVersion,
		"schema_version":  SchemaVersion,
		"mode":            Mode,
		"status":          "RECEIVED",
		"http_status":     202,
		"request_id":      requestID,
		"duplicate":       duplicate,
		"callback_status": callbackStatus,
		"result_path":     inboundPath + "/" + url.PathEscape(requestID),
		"production_send": ProductionSend,
		"received_at":     receivedAt.Format(time.RFC3339),
	}
}

func shadowCallbackPayload(req inboundRequest, status string, confidence string, reason string) map[string]any {
	return map[string]any{
		"api_version": APIVersion,
		"schema_version": SchemaVersion,
		"mode": Mode,
		"request_id": req.RequestID,
		"status": status,
		"confidence": confidence,
		"received": map[string]any{
			"meter_ref": map[string]any{"hash": hashMeter(req.MeterNo), "last4": last4(req.MeterNo)},
			"site_ref":    map[string]any{"hash": hashOptional(req.SiteID), "last4": last4(req.SiteID)},
			"detected_at": req.DetectedAt.Format(time.RFC3339),
			"province": req.Province,
			"district": req.District,
			"subdistrict": req.Subdistrict,
		},
		"truth_observation": map[string]any{
			"source":             "AIS",
			"source_event_id":    req.SourceEventID,
			"event_type":         req.EventType,
			"outage_at":          formatTimePtr(req.OutageAt),
			"restore_at":         formatTimePtr(req.RestoreAt),
			"validation_status":  req.TruthValidation,
			"truth_target":       "ais_site_actual_restoration_minutes",
			"production_send":    ProductionSend,
		},
		"pea_distribution": map[string]any{"status": status, "reason": reason, "cause_lane": classifyCause(req)},
		"evidence": map[string]any{
			"source": "go_cloud_shadow_api",
			"match_found": false,
			"match_level": "",
			"match_confidence": 0,
			"reason": "python_worker_pending_or_no_evidence_loaded",
		},
		"etr": map[string]any{
			"status": "NOT_READY_FOR_AUTO_SEND",
			"model_version": "shadow",
			"production_gate": "blocked_green_gate",
		},
		"decision": map[string]any{
			"answer": "REVIEW_REQUIRED",
			"reason": "cloud_api_captured_request_but_auto_etr_gate_blocked",
			"auto_customer_etr_allowed": false,
			"production_send": ProductionSend,
			"next_action": "review_evidence_before_any_customer_facing_etr",
		},
		"generated_at": nowISO(),
	}
}

func duplicateCallbackPayload(req inboundRequest) map[string]any {
	payload := shadowCallbackPayload(req, "DUPLICATE_REQUEST", "INFO", "request_id_already_received")
	payload["decision"] = map[string]any{
		"answer": "DUPLICATE_REQUEST",
		"reason": "request_id_already_received",
		"auto_customer_etr_allowed": false,
		"production_send": ProductionSend,
		"next_action": "query_existing_request_status",
	}
	payload["etr"] = map[string]any{"status": "NOT_READY_FOR_AUTO_SEND", "model_version": "shadow", "production_gate": "blocked_green_gate"}
	return payload
}

func classifyCause(req inboundRequest) string {
	combined := strings.ToLower(req.MainCause + " " + req.Subcause + " " + req.AlarmType)
	switch {
	case strings.Contains(combined, "pea no back") || strings.Contains(combined, "no backup"):
		return "pea_no_backup"
	case strings.Contains(combined, "planned") || strings.Contains(combined, "activity"):
		return "pea_activity_or_planned"
	case strings.Contains(combined, "battery") || strings.Contains(combined, "rectifier"):
		return "ais_equipment_or_backup"
	default:
		return "unknown"
	}
}

func statusPayload(row *storage.RequestStatus) map[string]any {
	result := map[string]any{}
	_ = json.Unmarshal(row.CallbackPayload, &result)
	timestampQuality := map[string]any{}
	_ = json.Unmarshal(row.TimestampQuality, &timestampQuality)
	return map[string]any{
		"api_version": APIVersion,
		"schema_version": SchemaVersion,
		"mode": Mode,
		"request_id": row.RequestID,
		"status": map[bool]string{true: "COMPLETED", false: "RECEIVED"}[len(row.CallbackPayload) > 0],
		"request_status": "RECEIVED",
		"callback_status": row.RequestCallback,
		"production_send": ProductionSend,
		"received_at": row.ReceivedAt.Format(time.RFC3339),
		"detected_at": row.DetectedAt.Format(time.RFC3339),
		"detected_at_original": row.DetectedAtOriginal,
		"timestamp_quality": timestampQuality,
		"meter": map[string]any{"hash": row.MeterHash, "last4": row.MeterLast4},
		"site": map[string]any{"hash": row.TruthSiteHash, "last4": row.TruthSiteLast4},
		"area": map[string]any{"province": row.Province, "district": row.District, "subdistrict": row.Subdistrict},
		"truth_observation": map[string]any{
			"source":            "AIS",
			"source_event_id":   row.TruthSourceEventID,
			"event_type":        row.TruthEventType,
			"validation_status": row.TruthValidation,
			"production_send":   ProductionSend,
		},
		"result": result,
		"last_callback": map[string]any{
			"status": row.LatestCallback,
			"status_code": row.CallbackStatusCode,
			"sent_at": row.CallbackSentAt,
		},
		"etr_status": row.ETRStatus,
		"send_control": map[string]any{
			"policy_mode":        blankDefault(row.SendPolicyMode, "blocked"),
			"effective_mode":     blankDefault(row.SendEffectiveMode, "blocked"),
			"eligibility_status": blankDefault(row.EligibilityStatus, "red_blocked"),
			"decision":           blankDefault(row.SendDecision, "blocked"),
			"reason":             blankDefault(row.SendReason, "production_send_blocked_by_default"),
			"gate_version":       blankDefault(row.SendGateVersion, "blocked_green_gate"),
			"production_send":    ProductionSend,
		},
		"callback_outbox": map[string]any{
			"status":    row.CallbackOutboxStatus,
			"transport": blankDefault(row.CallbackTransport, "dry_run"),
			"attempts":  row.CallbackAttempts,
		},
	}
}

func errorPayload(code, message, requestID string) map[string]any {
	payload := map[string]any{
		"api_version": APIVersion,
		"schema_version": SchemaVersion,
		"mode": Mode,
		"status": "ERROR",
		"error": map[string]string{"code": code, "message": message},
		"production_send": ProductionSend,
		"generated_at": nowISO(),
	}
	if requestID != "" {
		payload["request_id"] = requestID
	}
	return payload
}

func writeJSON(w http.ResponseWriter, status int, payload map[string]any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func redactPayload(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		result := map[string]any{}
		for key, item := range typed {
			lower := strings.ToLower(key)
			switch {
			case lower == "meter_no" || lower == "meterno" || lower == "peano":
				text := fmt.Sprint(item)
				result[key] = map[string]string{"hash": hashMeter(text), "last4": last4(text)}
			case lower == "site_id" || lower == "siteid" || lower == "location_id" || lower == "locationid":
				text := fmt.Sprint(item)
				result[key] = map[string]string{"hash": hashOptional(text), "last4": last4(text)}
			case strings.Contains(lower, "token") || strings.Contains(lower, "secret") || strings.Contains(lower, "key") || strings.Contains(lower, "roomid"):
				result[key] = "REDACTED"
			case lower == "raw":
				result[key] = "REDACTED"
			default:
				result[key] = redactPayload(item)
			}
		}
		return result
	case []any:
		items := make([]any, 0, len(typed))
		for _, item := range typed {
			items = append(items, redactPayload(item))
		}
		return items
	default:
		return value
	}
}

func hashMeter(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])[:16]
}

func hashOptional(value string) string {
	if strings.TrimSpace(value) == "" {
		return ""
	}
	return hashMeter(value)
}

func hashRaw(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

func blankDefault(value string, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func last4(value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	if len(value) <= 4 {
		return value
	}
	return value[len(value)-4:]
}

func formatTimePtr(value *time.Time) string {
	if value == nil {
		return ""
	}
	return value.Format(time.RFC3339)
}

func normalizeTruthEventType(payload map[string]any, alarmType string, mainCause string, subcause string) string {
	raw := strings.ToLower(strings.Join([]string{
		firstText(payload, "event_type", "eventType", "power_status", "powerStatus", "event_status", "eventStatus", "status"),
		alarmType,
		mainCause,
		subcause,
	}, " "))
	switch {
	case containsAny(raw, "restore", "restored", "recover", "recovered", "power_on", "power on", "normal", "\u0e01\u0e25\u0e31\u0e1a\u0e04\u0e37\u0e19", "\u0e08\u0e48\u0e32\u0e22\u0e44\u0e1f"):
		return "RESTORE"
	case containsAny(raw, "outage", "power_off", "power off", "fail", "failure", "down", "ac main fail", "\u0e14\u0e31\u0e1a", "\u0e44\u0e1f\u0e14\u0e31\u0e1a"):
		return "OUTAGE"
	case strings.TrimSpace(raw) != "":
		return "STATUS"
	default:
		return "UNKNOWN"
	}
}

func containsAny(value string, needles ...string) bool {
	for _, needle := range needles {
		if strings.Contains(value, needle) {
			return true
		}
	}
	return false
}

func truthValidationStatus(eventType string, outageAt *time.Time, restoreAt *time.Time) string {
	if eventType == "UNKNOWN" || eventType == "STATUS" {
		return "REVIEW_EVENT_TYPE"
	}
	if outageAt != nil && restoreAt != nil && restoreAt.Before(*outageAt) {
		return "REVIEW_RESTORE_BEFORE_OUTAGE"
	}
	return "READY_FOR_LEDGER"
}

func truthSummaryPayload(req inboundRequest) map[string]any {
	return map[string]any{
		"source":            "AIS",
		"source_event_id":   req.SourceEventID,
		"event_type":        req.EventType,
		"detected_at":       req.DetectedAt.Format(time.RFC3339),
		"outage_at":         formatTimePtr(req.OutageAt),
		"restore_at":        formatTimePtr(req.RestoreAt),
		"timestamp_quality": req.TimestampQuality,
		"area_present":      req.Province != "" || req.District != "" || req.Subdistrict != "",
		"site_ref_present":  req.SiteID != "",
		"meter_ref":         map[string]any{"hash": hashMeter(req.MeterNo), "last4": last4(req.MeterNo)},
		"site_ref":          map[string]any{"hash": hashOptional(req.SiteID), "last4": last4(req.SiteID)},
	}
}

func mustJSON(value any) json.RawMessage {
	data, err := json.Marshal(value)
	if err != nil {
		return json.RawMessage(`{}`)
	}
	return data
}

func nowISO() string {
	return time.Now().UTC().Format(time.RFC3339)
}

func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err == nil {
		return host
	}
	return r.RemoteAddr
}

func correlationID(r *http.Request, fallback string) string {
	value := strings.TrimSpace(r.Header.Get("X-Correlation-ID"))
	if value == "" || len(value) > 128 || !safeID.MatchString(value) {
		return fallback
	}
	return value
}

type rateLimiter struct {
	limit int
	mu    sync.Mutex
	hits  map[string]bucket
}

type bucket struct {
	minute int64
	count  int
}

func newRateLimiter(limit int) *rateLimiter {
	return &rateLimiter{limit: limit, hits: map[string]bucket{}}
}

func (r *rateLimiter) allow(key string) (bool, int) {
	if r.limit == 0 {
		return true, 0
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	nowMinute := time.Now().Unix() / 60
	item := r.hits[key]
	if item.minute != nowMinute {
		item = bucket{minute: nowMinute}
	}
	item.count++
	r.hits[key] = item
	if item.count > r.limit {
		return false, int(60 - time.Now().Unix()%60)
	}
	return true, 0
}
