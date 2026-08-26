package api

import (
	"context"
	"errors"
	"net/http"
	"net/url"
	"strings"

	"pea-api-intellisense/apps/api-go/internal/correlation"
	"pea-api-intellisense/apps/api-go/internal/storage"
)

const chatbotCorrelationSchema = "pea-chatbot-correlation-status.v1"

type correlationStatusStore interface {
	GetCorrelationReportSnapshot(context.Context, string) (*storage.CorrelationReportSnapshot, error)
	GetLatestCorrelationJobForReport(context.Context, string) (*storage.CorrelationJob, error)
	GetLatestCorrelationMembership(context.Context, string) (*storage.CorrelationMembershipRevision, error)
	GetLatestCorrelationClusterRevision(context.Context, string) (*storage.CorrelationClusterRevision, error)
}

func (s *Server) handleChatbotCorrelationStatus(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	path := strings.TrimPrefix(r.URL.Path, chatbotReportsPath+"/")
	if !strings.HasSuffix(path, "/correlation") {
		writeJSON(w, http.StatusNotFound, errorPayload("NOT_FOUND", "Unknown endpoint", ""))
		return
	}
	rawTicket := strings.TrimSuffix(path, "/correlation")
	ticketID, err := url.PathUnescape(rawTicket)
	if err != nil || !chatbotTicketIDPattern.MatchString(ticketID) || strings.Contains(ticketID, "/") {
		writeJSON(w, http.StatusOK, chatbotCorrelationNotFoundPayload(ticketID))
		return
	}

	requestID := outageRequestID(chatbotInternalChannel, ticketID)
	_, err = s.store.GetBuengKanOutageResolution(r.Context(), requestID)
	if errors.Is(err, storage.ErrNotFound) {
		writeJSON(w, http.StatusOK, chatbotCorrelationNotFoundPayload(ticketID))
		return
	}
	if err != nil {
		s.cfg.Logger.Error("chatbot correlation core lookup failed", "request_ref", hashReference("request", requestID), "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load chatbot report state", requestID))
		return
	}

	store, ok := s.store.(correlationStatusStore)
	if !ok {
		writeJSON(w, http.StatusOK, chatbotCorrelationUnavailablePayload(ticketID, "CORRELATION_STORE_UNAVAILABLE"))
		return
	}
	reportID := hashReference("correlation_report", "n8n-pea-buengkan|"+ticketID)
	snapshot, err := store.GetCorrelationReportSnapshot(r.Context(), reportID)
	if errors.Is(err, storage.ErrNotFound) {
		reason := "CORRELATION_NOT_CAPTURED"
		if normalizeIncidentCorrelationMode(s.cfg.IncidentCorrelationMode) != "shadow" {
			reason = "CORRELATION_DISABLED"
		}
		writeJSON(w, http.StatusOK, chatbotCorrelationUnavailablePayload(ticketID, reason))
		return
	}
	if err != nil {
		s.cfg.Logger.Error("chatbot correlation snapshot lookup failed", "report_ref", hashReference("correlation_report_ref", reportID), "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load correlation status", requestID))
		return
	}

	job, err := store.GetLatestCorrelationJobForReport(r.Context(), reportID)
	if errors.Is(err, storage.ErrNotFound) {
		writeJSON(w, http.StatusOK, chatbotCorrelationUnavailablePayload(ticketID, "CORRELATION_JOB_MISSING"))
		return
	}
	if err != nil {
		s.cfg.Logger.Error("chatbot correlation job lookup failed", "report_ref", hashReference("correlation_report_ref", reportID), "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load correlation status", requestID))
		return
	}

	switch strings.ToUpper(strings.TrimSpace(job.State)) {
	case "PENDING", "PROCESSING", "RETRYING":
		writeJSON(w, http.StatusOK, chatbotCorrelationSafePayload(ticketID, "PENDING", snapshot, nil, nil, ""))
		return
	case "FAILED":
		writeJSON(w, http.StatusOK, chatbotCorrelationUnavailablePayload(ticketID, "CORRELATION_PROCESSING_FAILED"))
		return
	case "SUCCEEDED":
		// Continue to the durable membership projection below.
	default:
		writeJSON(w, http.StatusOK, chatbotCorrelationUnavailablePayload(ticketID, "CORRELATION_JOB_STATE_UNKNOWN"))
		return
	}

	if snapshot.Evidence.PlannedOutageState == correlation.PlannedMatched {
		writeJSON(w, http.StatusOK, chatbotCorrelationSafePayload(ticketID, "PLANNED_OUTAGE_LINKED", snapshot, nil, nil, ""))
		return
	}

	membership, err := store.GetLatestCorrelationMembership(r.Context(), reportID)
	if errors.Is(err, storage.ErrNotFound) {
		writeJSON(w, http.StatusOK, chatbotCorrelationSafePayload(ticketID, "NO_CLUSTER", snapshot, nil, nil, ""))
		return
	}
	if err != nil {
		s.cfg.Logger.Error("chatbot correlation membership lookup failed", "report_ref", hashReference("correlation_report_ref", reportID), "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load correlation status", requestID))
		return
	}
	if strings.ToUpper(strings.TrimSpace(membership.MembershipState)) != "ACTIVE" || strings.TrimSpace(membership.ClusterID) == "" {
		writeJSON(w, http.StatusOK, chatbotCorrelationSafePayload(ticketID, "NO_CLUSTER", snapshot, membership, nil, ""))
		return
	}

	clusterRevision, err := store.GetLatestCorrelationClusterRevision(r.Context(), membership.ClusterID)
	if errors.Is(err, storage.ErrNotFound) {
		writeJSON(w, http.StatusOK, chatbotCorrelationUnavailablePayload(ticketID, "CORRELATION_CLUSTER_REVISION_MISSING"))
		return
	}
	if err != nil {
		s.cfg.Logger.Error("chatbot correlation cluster lookup failed", "cluster_ref", hashReference("correlation_cluster", membership.ClusterID), "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load correlation status", requestID))
		return
	}
	state := strings.ToUpper(strings.TrimSpace(clusterRevision.CorrelationStatus))
	if state != "SUSPECTED_RELATED" && state != "MULTIPLE_CLUSTER_CANDIDATES" {
		state = "SUSPECTED_RELATED"
	}
	writeJSON(w, http.StatusOK, chatbotCorrelationSafePayload(ticketID, state, snapshot, membership, clusterRevision, membership.ClusterID))
}

func chatbotCorrelationNotFoundPayload(ticketID string) map[string]any {
	return map[string]any{
		"schema_version": chatbotCorrelationSchema,
		"ticket_id":      ticketID,
		"found":          false,
		"correlation": map[string]any{
			"available": false,
			"state":     "NOT_FOUND",
		},
		"bot_action":             "NO_CUSTOMER_ACTION",
		"customer_truth_changed": false,
		"mode":                   Mode,
		"production_send":        ProductionSend,
	}
}

func chatbotCorrelationUnavailablePayload(ticketID, reason string) map[string]any {
	return map[string]any{
		"schema_version": chatbotCorrelationSchema,
		"ticket_id":      ticketID,
		"found":          true,
		"correlation": map[string]any{
			"available":   false,
			"state":       "UNAVAILABLE",
			"reason_code": reason,
		},
		"bot_action":                     "NO_CUSTOMER_ACTION",
		"customer_truth_changed":         false,
		"operational_incident_confirmed": false,
		"root_cause_confirmed":           false,
		"mode":                           Mode,
		"production_send":                ProductionSend,
	}
}

func chatbotCorrelationSafePayload(ticketID, state string, snapshot *storage.CorrelationReportSnapshot, membership *storage.CorrelationMembershipRevision, cluster *storage.CorrelationClusterRevision, clusterID string) map[string]any {
	correlationPayload := map[string]any{
		"available":            true,
		"state":                state,
		"confidence_level":     "",
		"cluster_ref":          "",
		"cluster_revision":     0,
		"lifecycle_state":      "",
		"report_count":         0,
		"planned_outage_state": snapshot.Evidence.PlannedOutageState,
		"engine_version":       snapshot.Evidence.SourceVersion,
	}
	if membership != nil {
		correlationPayload["confidence_level"] = membership.ConfidenceLevel
		correlationPayload["engine_version"] = membership.EngineVersion
	}
	if cluster != nil {
		correlationPayload["confidence_level"] = cluster.ConfidenceLevel
		correlationPayload["cluster_revision"] = cluster.Revision
		correlationPayload["lifecycle_state"] = cluster.LifecycleState
		correlationPayload["report_count"] = cluster.RawReportCount
		correlationPayload["engine_version"] = cluster.EngineVersion
	}
	if clusterID != "" {
		correlationPayload["cluster_ref"] = hashReference("correlation_cluster", clusterID)
	}
	return map[string]any{
		"schema_version":                 chatbotCorrelationSchema,
		"ticket_id":                      ticketID,
		"found":                          true,
		"correlation":                    correlationPayload,
		"bot_action":                     "NO_CUSTOMER_ACTION",
		"customer_truth_changed":         false,
		"operational_incident_confirmed": false,
		"root_cause_confirmed":           false,
		"mode":                           Mode,
		"production_send":                ProductionSend,
	}
}
