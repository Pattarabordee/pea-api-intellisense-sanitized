package api

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"pea-api-intellisense/apps/api-go/internal/buengkan"
	"pea-api-intellisense/apps/api-go/internal/storage"
)

const (
	chatbotReportsPath     = "/api/v1/chatbot-reports"
	chatbotRequestSchema   = "pea-chatbot-report.v1"
	chatbotAckSchema       = "pea-chatbot-report-ack.v1"
	chatbotStatusSchema    = "pea-chatbot-report-status.v1"
	chatbotInternalChannel = "N8N"
)

var (
	chatbotTicketIDPattern   = regexp.MustCompile(`^PEA-[0-9]{8}-[A-F0-9]{6}$`)
	chatbotSessionRefPattern = regexp.MustCompile("^sha256:[A-Fa-f0-9]{64}$")
	chatbotMooPattern        = regexp.MustCompile(`(?:หมู่|ม\.)\s*([0-9]{1,2})`)
)

type chatbotSourceInput struct {
	System     string `json:"system"`
	Channel    string `json:"channel"`
	EventID    string `json:"event_id"`
	SessionRef string `json:"session_ref"`
	OccurredAt string `json:"occurred_at"`
}

type chatbotLocationInput struct {
	HouseOrVillage string `json:"house_or_village"`
	Subdistrict    string `json:"subdistrict"`
	District       string `json:"district"`
	Province       string `json:"province"`
}

type chatbotCustomerInput struct {
	Name  string `json:"name"`
	Phone string `json:"phone"`
}

type chatbotReportInput struct {
	TicketID       string               `json:"ticket_id"`
	ServiceType    string               `json:"service_type"`
	IncidentDetail string               `json:"incident_detail"`
	Location       chatbotLocationInput `json:"location"`
	Customer       chatbotCustomerInput `json:"customer"`
	Confirmed      bool                 `json:"confirmed"`
	CompletedAt    string               `json:"completed_at"`
}

type chatbotReportRequest struct {
	SchemaVersion string             `json:"schema_version"`
	Source        chatbotSourceInput `json:"source"`
	Report        chatbotReportInput `json:"report"`
}

type capturedResponse struct {
	header http.Header
	status int
	body   bytes.Buffer
}

func newCapturedResponse() *capturedResponse {
	return &capturedResponse{header: make(http.Header)}
}

func (c *capturedResponse) Header() http.Header { return c.header }

func (c *capturedResponse) WriteHeader(status int) {
	if c.status == 0 {
		c.status = status
	}
}

func (c *capturedResponse) Write(data []byte) (int, error) {
	if c.status == 0 {
		c.status = http.StatusOK
	}
	return c.body.Write(data)
}

func (s *Server) handleChatbotReport(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	if !strings.Contains(strings.ToLower(r.Header.Get("Content-Type")), "application/json") {
		writeJSON(w, http.StatusUnsupportedMediaType, errorPayload("UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json", ""))
		return
	}
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, 128_000))
	decoder.DisallowUnknownFields()
	var input chatbotReportRequest
	if err := decoder.Decode(&input); err != nil {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_REQUEST", "Request body must match pea-chatbot-report.v1 JSON schema", ""))
		return
	}
	if err := validateChatbotReportRequest(&input); err != nil {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_REQUEST", err.Error(), ""))
		return
	}

	requestID := outageRequestID(chatbotInternalChannel, input.Report.TicketID)
	message := chatbotOutageMessage(input.Report)
	preflight := buengkan.Resolve(message)
	if field := chatbotLocationCorrectionField(input.Report.Location, preflight); field != "" {
		writeJSON(w, http.StatusOK, chatbotNeedsMoreInfoPayload(input.Report.TicketID, requestID, field))
		return
	}

	internal := outageResolveRequest{
		SchemaVersion: outageContractVersion,
		Source: outageSourceInput{
			Channel:     chatbotInternalChannel,
			EventID:     input.Report.TicketID,
			OccurredAt:  input.Source.OccurredAt,
			ReporterRef: input.Source.SessionRef,
		},
		Message: outageMessageInput{Text: message},
		Hints: &outageHintsInput{
			Province:         input.Report.Location.Province,
			District:         input.Report.Location.District,
			Subdistrict:      input.Report.Location.Subdistrict,
			VillageCandidate: input.Report.Location.HouseOrVillage,
			Source:           "n8n_handoff_adapter",
		},
	}
	body, err := json.Marshal(internal)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not encode internal outage request", requestID))
		return
	}
	internalReq := r.Clone(r.Context())
	internalURL := *r.URL
	internalURL.Path = outageResolvePath
	internalURL.RawPath = ""
	internalURL.RawQuery = ""
	internalReq.URL = &internalURL
	internalReq.Method = http.MethodPost
	internalReq.Body = io.NopCloser(bytes.NewReader(body))
	internalReq.ContentLength = int64(len(body))
	internalReq.Header = r.Header.Clone()
	internalReq.Header.Set("Content-Type", "application/json; charset=utf-8")

	captured := newCapturedResponse()
	s.handleBuengKanOutageResolve(captured, internalReq)
	if retryAfter := captured.Header().Get("Retry-After"); retryAfter != "" {
		w.Header().Set("Retry-After", retryAfter)
	}
	if captured.status >= 400 {
		var payload map[string]any
		if json.Unmarshal(captured.body.Bytes(), &payload) != nil {
			writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Internal outage resolver returned an invalid response", requestID))
			return
		}
		writeJSON(w, captured.status, payload)
		return
	}
	var resolved map[string]any
	if err := json.Unmarshal(captured.body.Bytes(), &resolved); err != nil {
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Internal outage resolver returned an invalid response", requestID))
		return
	}
	ack := chatbotAckFromOutageResult(input.Report.TicketID, resolved)
	writeJSON(w, captured.status, ack)
}

func (s *Server) handleChatbotReportStatus(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	path := strings.TrimPrefix(r.URL.Path, chatbotReportsPath+"/")
	if !strings.HasSuffix(path, "/status") {
		writeJSON(w, http.StatusNotFound, errorPayload("NOT_FOUND", "Unknown endpoint", ""))
		return
	}
	rawTicket := strings.TrimSuffix(path, "/status")
	ticketID, err := url.PathUnescape(rawTicket)
	if err != nil || !chatbotTicketIDPattern.MatchString(ticketID) || strings.Contains(ticketID, "/") {
		writeJSON(w, http.StatusOK, chatbotStatusNotFoundPayload(ticketID))
		return
	}
	requestID := outageRequestID(chatbotInternalChannel, ticketID)
	_, err = s.store.GetBuengKanOutageResolution(r.Context(), requestID)
	if errors.Is(err, storage.ErrNotFound) {
		writeJSON(w, http.StatusOK, chatbotStatusNotFoundPayload(ticketID))
		return
	}
	if err != nil {
		s.cfg.Logger.Error("chatbot report status lookup failed", "request_ref", hashReference("request", requestID), "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load chatbot report status", requestID))
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"schema_version": chatbotStatusSchema,
		"ticket_id":      ticketID,
		"found":          true,
		"bot_action":     "SHOW_STATUS",
		"customer_message": map[string]any{
			"template_key": "STATUS_RECEIVED",
			"params":       map[string]any{},
		},
	})
}

func validateChatbotReportRequest(input *chatbotReportRequest) error {
	if input.SchemaVersion != chatbotRequestSchema {
		return errors.New("schema_version must be pea-chatbot-report.v1")
	}
	if strings.TrimSpace(input.Source.System) != "n8n-pea-buengkan" {
		return errors.New("source.system must be n8n-pea-buengkan")
	}
	channel := strings.ToLower(strings.TrimSpace(input.Source.Channel))
	if channel != "line" && channel != "chat" {
		return errors.New("source.channel must be line or chat")
	}
	if !chatbotTicketIDPattern.MatchString(strings.TrimSpace(input.Report.TicketID)) {
		return errors.New("report.ticket_id must match PEA-YYYYMMDD-XXXXXX")
	}
	if strings.TrimSpace(input.Source.EventID) != strings.TrimSpace(input.Report.TicketID) {
		return errors.New("source.event_id must equal report.ticket_id")
	}
	if !chatbotSessionRefPattern.MatchString(strings.TrimSpace(input.Source.SessionRef)) {
		return errors.New("source.session_ref must be a sha256: reference")
	}
	if _, err := time.Parse(time.RFC3339, strings.TrimSpace(input.Source.OccurredAt)); err != nil {
		return errors.New("source.occurred_at must be RFC3339 with timezone")
	}
	if input.Report.ServiceType != "power_outage" {
		return errors.New("report.service_type must be power_outage for PEA Intellisense compatibility adapter v1")
	}
	if err := boundedChatbotText(input.Report.IncidentDetail, 300, true); err != nil {
		return errors.New("report.incident_detail is required and must be <= 300 characters")
	}
	for name, value := range map[string]string{
		"house_or_village": input.Report.Location.HouseOrVillage,
		"subdistrict":      input.Report.Location.Subdistrict,
		"district":         input.Report.Location.District,
		"province":         input.Report.Location.Province,
	} {
		limit := 80
		if name == "house_or_village" {
			limit = 200
		}
		if err := boundedChatbotText(value, limit, true); err != nil {
			return errors.New("report.location." + name + " is required and exceeds the contract limit")
		}
	}
	if err := boundedChatbotText(input.Report.Customer.Name, 120, true); err != nil {
		return errors.New("report.customer.name is required and must be <= 120 characters")
	}
	phone := strings.TrimSpace(input.Report.Customer.Phone)
	if len(phone) < 9 || len(phone) > 10 {
		return errors.New("report.customer.phone must contain 9 to 10 digits")
	}
	for _, r := range phone {
		if r < '0' || r > '9' {
			return errors.New("report.customer.phone must contain digits only")
		}
	}
	if !input.Report.Confirmed {
		return errors.New("report.confirmed must be true")
	}
	if _, err := time.Parse(time.RFC3339, strings.TrimSpace(input.Report.CompletedAt)); err != nil {
		return errors.New("report.completed_at must be RFC3339")
	}
	return nil
}

func boundedChatbotText(value string, max int, required bool) error {
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

func chatbotOutageMessage(report chatbotReportInput) string {
	parts := []string{
		strings.TrimSpace(report.IncidentDetail),
		strings.TrimSpace(report.Location.HouseOrVillage),
		strings.TrimSpace(report.Location.Subdistrict),
		strings.TrimSpace(report.Location.District),
		strings.TrimSpace(report.Location.Province),
	}
	return strings.Join(parts, " ")
}

func chatbotLocationCorrectionField(location chatbotLocationInput, preflight buengkan.ResolveResult) string {
	if normalizeChatbotAdmin(location.Province, "จังหวัด", "จ.") != "บึงกาฬ" {
		return "province"
	}
	district := normalizeChatbotAdmin(location.District, "อำเภอ", "อ.")
	if district != "บึงกาฬ" && district != "เมืองบึงกาฬ" {
		return "district"
	}
	if normalizeChatbotAdmin(location.Subdistrict, "ตำบล", "ต.") != "บึงกาฬ" {
		return "subdistrict"
	}
	if match := chatbotMooPattern.FindStringSubmatch(location.HouseOrVillage); len(match) == 2 && preflight.VillageKey != "" {
		parts := strings.Split(preflight.VillageKey, "-M")
		if len(parts) == 2 {
			expected := strings.TrimLeft(parts[1], "0")
			if expected == "" {
				expected = "0"
			}
			actual := strings.TrimLeft(match[1], "0")
			if actual == "" {
				actual = "0"
			}
			if actual != expected {
				return "house_or_village"
			}
		}
	}
	switch preflight.Status {
	case "OUTSIDE_PILOT_SCOPE", "AMBIGUOUS_VILLAGE", "AMBIGUOUS_FOOTPRINT":
		return "house_or_village"
	default:
		return ""
	}
}

func normalizeChatbotAdmin(value string, prefixes ...string) string {
	value = strings.TrimSpace(value)
	for _, prefix := range prefixes {
		value = strings.TrimSpace(strings.TrimPrefix(value, prefix))
	}
	return value
}

func chatbotNeedsMoreInfoPayload(ticketID, requestID, field string) map[string]any {
	return map[string]any{
		"schema_version": chatbotAckSchema,
		"ticket_id":      ticketID,
		"request_id":     requestID,
		"duplicate":      false,
		"accept_status":  "NEEDS_MORE_INFO",
		"bot_action":     "ASK_MORE_LOCATION",
		"customer_message": map[string]any{
			"template_key": "NEED_LOCATION",
			"params": map[string]any{
				"missing_field": field,
			},
		},
		"context": map[string]any{
			"outage_state": "UNDETERMINED",
		},
	}
}

func chatbotAckFromOutageResult(ticketID string, resolved map[string]any) map[string]any {
	requestID, _ := resolved["request_id"].(string)
	duplicate, _ := resolved["duplicate"].(bool)
	context := map[string]any{"outage_state": "UNDETERMINED"}
	if resolution, ok := resolved["resolution"].(map[string]any); ok {
		if outageState, ok := resolution["outage_state"].(string); ok && outageState != "" {
			context["outage_state"] = outageState
		}
		if feeder, ok := resolution["selected_feeder"].(string); ok && feeder != "" {
			context["feeder_id"] = feeder
		}
		if selected, ok := resolution["selected_transformers"].([]any); ok && len(selected) == 1 {
			if tx, ok := selected[0].(map[string]any); ok {
				if facilityID, ok := tx["facility_id"].(string); ok && facilityID != "" {
					context["transformer_id"] = facilityID
				}
			}
		}
	}
	return map[string]any{
		"schema_version": chatbotAckSchema,
		"ticket_id":      ticketID,
		"request_id":     requestID,
		"duplicate":      duplicate,
		"accept_status":  "ACCEPTED",
		"bot_action":     "SHOW_ACK",
		"customer_message": map[string]any{
			"template_key": "ACK",
			"params":       map[string]any{},
		},
		"context": context,
	}
}

func chatbotStatusNotFoundPayload(ticketID string) map[string]any {
	return map[string]any{
		"schema_version": chatbotStatusSchema,
		"ticket_id":      ticketID,
		"found":          false,
		"bot_action":     "STATUS_NOT_FOUND",
		"customer_message": map[string]any{
			"template_key": "STATUS_NOT_FOUND",
			"params":       map[string]any{},
		},
	}
}
