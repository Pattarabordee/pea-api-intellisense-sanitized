package api

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"pea-api-intellisense/apps/api-go/internal/buengkan"
	"pea-api-intellisense/apps/api-go/internal/storage"
)

const (
	outageResolvePath       = "/api/v1/outage-reports/resolve"
	outageResultPathPrefix  = "/api/v1/outage-topology/results/"
	transformerPathPrefix   = "/api/v1/transformers/"
	outageContractVersion   = "outage-report.v1"
	outageResultSchema      = "outage-topology.v1"
	transformerAssetSchema  = "transformer-asset.v1"
)

type outageSourceInput struct {
	Channel         string `json:"channel"`
	EventID         string `json:"event_id"`
	OccurredAt      string `json:"occurred_at"`
	ReporterRef     string `json:"reporter_ref"`
	ConversationRef string `json:"conversation_ref"`
}

type outageMessageInput struct {
	Text string `json:"text"`
}

type outageLocationInput struct {
	Lat       *float64 `json:"lat"`
	Lon       *float64 `json:"lon"`
	AccuracyM *float64 `json:"accuracy_m"`
	Source    string   `json:"source"`
}

type outageHintsInput struct {
	Province             string   `json:"province"`
	District             string   `json:"district"`
	Subdistrict          string   `json:"subdistrict"`
	Moo                  string   `json:"moo"`
	VillageCandidate     string   `json:"village_candidate"`
	Road                 string   `json:"road"`
	Soi                  string   `json:"soi"`
	Landmark             string   `json:"landmark"`
	Confidence           *float64 `json:"confidence"`
	Source               string   `json:"source"`
}

type outageResolveRequest struct {
	SchemaVersion string               `json:"schema_version"`
	Source        outageSourceInput    `json:"source"`
	Message       outageMessageInput   `json:"message"`
	Location      *outageLocationInput `json:"location"`
	Hints         *outageHintsInput    `json:"hints"`
}

func (s *Server) handleBuengKanOutageResolve(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	if ok, retryAfter := s.limiter.allow(clientIP(r)); !ok {
		w.Header().Set("Retry-After", strconvItoa(retryAfter))
		writeJSON(w, http.StatusTooManyRequests, errorPayload("RATE_LIMITED", "Too many requests. Retry later.", ""))
		return
	}
	if !strings.Contains(strings.ToLower(r.Header.Get("Content-Type")), "application/json") {
		writeJSON(w, http.StatusUnsupportedMediaType, errorPayload("UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json", ""))
		return
	}
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, 128_000))
	decoder.DisallowUnknownFields()
	var input outageResolveRequest
	if err := decoder.Decode(&input); err != nil {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_REQUEST", "Request body must match outage-report.v1 JSON schema", ""))
		return
	}
	occurredAt, err := validateOutageResolveRequest(&input)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_REQUEST", err.Error(), ""))
		return
	}

	requestID := outageRequestID(input.Source.Channel, input.Source.EventID)
	var location *buengkan.LocationInput
	if input.Location != nil && input.Location.Lat != nil && input.Location.Lon != nil {
		location = &buengkan.LocationInput{Lat: *input.Location.Lat, Lon: *input.Location.Lon, AccuracyM: input.Location.AccuracyM, Source: strings.TrimSpace(input.Location.Source)}
	}
	result := buengkan.ResolveWithLocation(input.Message.Text, location)
	locationUsed := result.LocationEvidence != nil && result.LocationEvidence.UsedForTopology
	var placeLocation *buengkan.PlaceResolveLocationInput
	if input.Location != nil && input.Location.Lat != nil && input.Location.Lon != nil {
		placeLocation = &buengkan.PlaceResolveLocationInput{Lat: *input.Location.Lat, Lon: *input.Location.Lon, AccuracyM: input.Location.AccuracyM, Source: strings.TrimSpace(input.Location.Source)}
	}
	placeResolution := buengkan.ResolvePlace(input.Message.Text, placeLocation, 10)
	payload := map[string]any{
		"api_version":     APIVersion,
		"schema_version":  outageResultSchema,
		"registry_version": buengkan.RegistryVersion(),
		"request_id":      requestID,
		"result_path":     outageResultPathPrefix + requestID,
		"duplicate":       false,
		"mode":            Mode,
		"production_send": ProductionSend,
		"source": map[string]any{
			"channel":      strings.ToUpper(strings.TrimSpace(input.Source.Channel)),
			"event_ref":    hashReference("source_event", input.Source.EventID),
			"occurred_at":  occurredAt.Format(time.RFC3339),
		},
		"input_evidence": map[string]any{
			"message_received":       true,
			"location_received":      input.Location != nil,
			"location_used_for_topology": locationUsed,
			"hints_received":         input.Hints != nil,
			"hints_used_for_topology": false,
			"place_evidence_matched":  placeResolution.MatchCount > 0,
			"place_evidence_used_for_topology": false,
		},
		"place_resolution": placeResolution,
		"resolution":   result,
		"generated_at": nowISO(),
	}
	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not encode topology result", requestID))
		return
	}
	duplicate, err := s.store.InsertBuengKanOutageResolution(r.Context(), storage.BuengKanOutageResolution{
		RequestID:           requestID,
		RecordedAt:          time.Now().UTC(),
		OccurredAt:          occurredAt,
		SourceChannel:       strings.ToUpper(strings.TrimSpace(input.Source.Channel)),
		SourceEventHash:     hashCompact("source_event", input.Source.EventID),
		MessageHash:         hashCompact("message", buengkan.NormalizeText(input.Message.Text)),
		ReporterRefHash:     hashCompact("reporter_ref", input.Source.ReporterRef),
		ConversationRefHash: hashCompact("conversation_ref", input.Source.ConversationRef),
		ResultJSON:          payloadJSON,
		Mode:                Mode,
		ProductionSend:      ProductionSend,
	})
	if err != nil {
		s.cfg.Logger.Error("buengkan outage resolution insert failed", "request_ref", hashReference("request", requestID), "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not persist topology result", requestID))
		return
	}
	if duplicate {
		stored, getErr := s.store.GetBuengKanOutageResolution(r.Context(), requestID)
		if getErr != nil {
			writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load existing topology result", requestID))
			return
		}
		storedPayload := map[string]any{}
		if err := json.Unmarshal(stored.ResultJSON, &storedPayload); err != nil {
			writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Stored topology result is invalid", requestID))
			return
		}
		storedPayload["duplicate"] = true
		writeJSON(w, http.StatusOK, storedPayload)
		return
	}
	w.Header().Set("Location", outageResultPathPrefix+requestID)
	writeJSON(w, http.StatusCreated, payload)
}

func (s *Server) handleBuengKanOutageResult(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	requestID, err := url.PathUnescape(strings.TrimPrefix(r.URL.Path, outageResultPathPrefix))
	if err != nil || !validOutageRequestID(requestID) {
		writeJSON(w, http.StatusNotFound, errorPayload("RESULT_NOT_FOUND", "No outage topology result was found", ""))
		return
	}
	row, err := s.store.GetBuengKanOutageResolution(r.Context(), requestID)
	if errors.Is(err, storage.ErrNotFound) {
		writeJSON(w, http.StatusNotFound, errorPayload("RESULT_NOT_FOUND", "No outage topology result was found", ""))
		return
	}
	if err != nil {
		s.cfg.Logger.Error("buengkan outage resolution lookup failed", "request_ref", hashReference("request", requestID), "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load topology result", ""))
		return
	}
	payload := map[string]any{}
	if err := json.Unmarshal(row.ResultJSON, &payload); err != nil {
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Stored topology result is invalid", ""))
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

func (s *Server) handleTransformerLookup(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	facilityID, err := url.PathUnescape(strings.TrimPrefix(r.URL.Path, transformerPathPrefix))
	facilityID = strings.ToUpper(strings.TrimSpace(facilityID))
	if err != nil || facilityID == "" || strings.Contains(facilityID, "/") || !safeID.MatchString(facilityID) {
		writeJSON(w, http.StatusNotFound, errorPayload("TRANSFORMER_NOT_FOUND", "Transformer was not found in the approved registry", ""))
		return
	}
	asset, err := buengkan.LookupTransformer(facilityID)
	if err != nil {
		writeJSON(w, http.StatusNotFound, errorPayload("TRANSFORMER_NOT_FOUND", "Transformer was not found in the approved registry", ""))
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"api_version":     APIVersion,
		"schema_version":  transformerAssetSchema,
		"registry_version": buengkan.RegistryVersion(),
		"mode":            Mode,
		"production_send": ProductionSend,
		"asset":           asset.Transformer,
		"service_villages": asset.ServiceVillages,
		"generated_at":    nowISO(),
	})
}

func (s *Server) authorizedOutage(r *http.Request) bool {
	key := strings.TrimSpace(s.cfg.OutageIntegrationAPIKey)
	if key != "" {
		if r.Header.Get("X-API-Key") == key {
			return true
		}
		auth := r.Header.Get("Authorization")
		if strings.HasPrefix(auth, "Bearer ") && strings.TrimPrefix(auth, "Bearer ") == key {
			return true
		}
	}
	return s.authorized(r)
}

func validateOutageResolveRequest(input *outageResolveRequest) (time.Time, error) {
	if input.SchemaVersion != "" && input.SchemaVersion != outageContractVersion {
		return time.Time{}, errors.New("schema_version must be outage-report.v1")
	}
	channel := strings.ToUpper(strings.TrimSpace(input.Source.Channel))
	allowedChannels := map[string]bool{"LINE": true, "FACEBOOK": true, "WEB": true, "WEB_TESTER": true, "N8N": true, "OTHER": true}
	if !allowedChannels[channel] {
		return time.Time{}, errors.New("source.channel must be LINE, FACEBOOK, WEB, WEB_TESTER, N8N, or OTHER")
	}
	if err := boundedOpaque(input.Source.EventID, 256, true); err != nil {
		return time.Time{}, errors.New("source.event_id is required and must be <= 256 characters without control characters")
	}
	occurredAt, err := time.Parse(time.RFC3339, strings.TrimSpace(input.Source.OccurredAt))
	if err != nil {
		return time.Time{}, errors.New("source.occurred_at must be RFC3339 with timezone")
	}
	if utf8.RuneCountInString(strings.TrimSpace(input.Message.Text)) == 0 || utf8.RuneCountInString(input.Message.Text) > 1000 {
		return time.Time{}, errors.New("message.text is required and must be <= 1000 characters")
	}
	for _, ref := range []string{input.Source.ReporterRef, input.Source.ConversationRef} {
		if strings.TrimSpace(ref) != "" && (len(ref) > 128 || !safeID.MatchString(ref)) {
			return time.Time{}, errors.New("reporter_ref and conversation_ref must be pseudonymous safe identifiers <= 128 characters")
		}
	}
	if input.Location != nil {
		if input.Location.Lat == nil || input.Location.Lon == nil || *input.Location.Lat < -90 || *input.Location.Lat > 90 || *input.Location.Lon < -180 || *input.Location.Lon > 180 {
			return time.Time{}, errors.New("location.lat/lon must be valid WGS84 coordinates")
		}
		if input.Location.AccuracyM != nil && (*input.Location.AccuracyM < 0 || *input.Location.AccuracyM > 100000) {
			return time.Time{}, errors.New("location.accuracy_m must be between 0 and 100000")
		}
		if utf8.RuneCountInString(input.Location.Source) > 64 {
			return time.Time{}, errors.New("location.source must be <= 64 characters")
		}
	}
	if input.Hints != nil {
		for _, value := range []string{input.Hints.Province, input.Hints.District, input.Hints.Subdistrict, input.Hints.Moo, input.Hints.VillageCandidate, input.Hints.Road, input.Hints.Soi, input.Hints.Landmark, input.Hints.Source} {
			if utf8.RuneCountInString(value) > 120 {
				return time.Time{}, errors.New("hints fields must be <= 120 characters")
			}
		}
		if input.Hints.Confidence != nil && (*input.Hints.Confidence < 0 || *input.Hints.Confidence > 1) {
			return time.Time{}, errors.New("hints.confidence must be between 0 and 1")
		}
	}
	return occurredAt.UTC(), nil
}

func boundedOpaque(value string, max int, required bool) error {
	value = strings.TrimSpace(value)
	if required && value == "" {
		return errors.New("required")
	}
	if utf8.RuneCountInString(value) > max {
		return errors.New("too long")
	}
	for _, r := range value {
		if unicode.IsControl(r) {
			return errors.New("control character")
		}
	}
	return nil
}

func outageRequestID(channel, eventID string) string {
	sum := sha256.Sum256([]byte(strings.ToUpper(strings.TrimSpace(channel)) + "|" + strings.TrimSpace(eventID)))
	return "out_" + hex.EncodeToString(sum[:])[:20]
}

func validOutageRequestID(value string) bool {
	if len(value) != 24 || !strings.HasPrefix(value, "out_") {
		return false
	}
	for _, r := range value[4:] {
		if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f')) {
			return false
		}
	}
	return true
}

func hashCompact(namespace, value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	sum := sha256.Sum256([]byte(namespace + "|" + value))
	return hex.EncodeToString(sum[:])[:20]
}

func strconvItoa(value int) string {
	if value == 0 { return "0" }
	const digits = "0123456789"
	buf := make([]byte, 0, 10)
	for value > 0 {
		buf = append(buf, digits[value%10])
		value /= 10
	}
	for i, j := 0, len(buf)-1; i < j; i, j = i+1, j-1 { buf[i], buf[j] = buf[j], buf[i] }
	return string(buf)
}
