package api

import (
	"context"
	"encoding/json"
	"strings"
	"time"

	"pea-api-intellisense/apps/api-go/internal/correlation"
	"pea-api-intellisense/apps/api-go/internal/storage"
)

type correlationAcceptanceStore interface {
	AcceptCorrelationReport(context.Context, storage.CorrelationReport, storage.CorrelationEvidenceRevision, storage.CorrelationJob) (string, int, bool, error)
}

func normalizeIncidentCorrelationMode(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "shadow":
		return "shadow"
	default:
		return "off"
	}
}

func (s *Server) captureCorrelationShadow(ctx context.Context, input chatbotReportRequest, resolved map[string]any, plannedState string) {
	if normalizeIncidentCorrelationMode(s.cfg.IncidentCorrelationMode) != "shadow" {
		return
	}
	store, ok := s.store.(correlationAcceptanceStore)
	if !ok {
		s.cfg.Logger.Debug("incident correlation shadow store capability unavailable")
		return
	}

	occurredAt, err := time.Parse(time.RFC3339, strings.TrimSpace(input.Source.OccurredAt))
	if err != nil {
		return
	}
	plannedState = normalizeCorrelationPlannedState(plannedState)
	reportID := hashReference("correlation_report", input.Source.System+"|"+input.Report.TicketID)
	requestID, _ := resolved["request_id"].(string)
	location := map[string]any{
		"province":    strings.TrimSpace(input.Report.Location.Province),
		"district":    strings.TrimSpace(input.Report.Location.District),
		"subdistrict": strings.TrimSpace(input.Report.Location.Subdistrict),
		"village":     correlationCanonicalVillage(resolved, input.Report.Location.HouseOrVillage),
	}
	topology := correlationTopologyFromResolved(resolved)
	freshness := map[string]any{
		"topology": correlation.FreshnessUnknown,
		"reason":   "core_topology_source_has_no_verified_freshness_timestamp_in_chatbot_v1",
	}
	evidenceBasis := map[string]any{
		"report_id":            reportID,
		"location":             location,
		"topology":             topology,
		"freshness":            freshness,
		"planned_outage_state": plannedState,
		"source_version":       correlation.EngineVersion,
	}
	evidenceRaw := mustJSON(evidenceBasis)
	evidenceHash := hashRaw(evidenceRaw)
	now := time.Now().UTC()
	report := storage.CorrelationReport{
		ReportID:               reportID,
		TicketID:               input.Report.TicketID,
		SourceSystem:           input.Source.System,
		SourceChannel:          strings.ToLower(strings.TrimSpace(input.Source.Channel)),
		SourceEventHash:        hashReference("chatbot_event", input.Source.EventID),
		SessionRefHash:         hashReference("chatbot_session", input.Source.SessionRef),
		OccurredAt:             occurredAt.UTC(),
		NormalizedLocationJSON: mustJSON(location),
		CoreRequestID:          requestID,
		PlannedOutageState:     plannedState,
		Mode:                   "shadow",
		ProductionSend:         ProductionSend,
		CreatedAt:              now,
	}
	evidence := storage.CorrelationEvidenceRevision{
		ReportID:           reportID,
		EvidenceHash:       evidenceHash,
		TopologyJSON:       mustJSON(topology),
		LocationJSON:       mustJSON(location),
		FreshnessJSON:      mustJSON(freshness),
		PlannedOutageState: plannedState,
		EvidenceQuality:    "CORE_TOPOLOGY_PROVISIONAL_FRESHNESS",
		RecordedAt:         now,
		SourceVersion:      correlation.EngineVersion,
	}
	job := storage.CorrelationJob{
		JobID:       hashReference("correlation_job", reportID+"|"+evidenceHash),
		ReportID:    reportID,
		JobType:     "REPORT_EVIDENCE_CHANGED",
		TriggerKey:  evidenceHash,
		State:       "PENDING",
		MaxAttempts: s.cfg.IncidentCorrelationMaxAttempts,
		AvailableAt: now,
		CreatedAt:   now,
	}
	storedID, revision, duplicate, err := store.AcceptCorrelationReport(ctx, report, evidence, job)
	if err != nil {
		// Correlation is deliberately non-gating. The outage ACK remains authoritative
		// for receipt even when this shadow lane cannot be persisted.
		s.cfg.Logger.Warn("incident correlation shadow capture failed",
			"ticket_ref", hashReference("chatbot_ticket", input.Report.TicketID), "error_class", "CORRELATION_CAPTURE_ERROR")
		return
	}
	s.cfg.Logger.Info("incident correlation shadow job queued",
		"report_ref", hashReference("correlation_report_ref", storedID),
		"evidence_revision", revision, "job_duplicate", duplicate,
		"planned_outage_state", plannedState, "engine_version", correlation.EngineVersion)
}

func correlationCanonicalVillage(resolved map[string]any, fallback string) string {
	fallback = strings.TrimSpace(fallback)
	resolution, ok := resolved["resolution"].(map[string]any)
	if !ok {
		return fallback
	}
	village, _ := resolution["village_name"].(string)
	village = strings.TrimSpace(village)
	if village == "" {
		return fallback
	}
	return village
}

func correlationTopologyFromResolved(resolved map[string]any) map[string]any {
	result := map[string]any{
		"feeder_id":               "",
		"transformer_ids":         []string{},
		"upstream_protection_ids": []string{},
		"authoritative":           true,
	}
	resolution, ok := resolved["resolution"].(map[string]any)
	if !ok {
		result["authoritative"] = false
		return result
	}
	if feeder, ok := resolution["selected_feeder"].(string); ok {
		result["feeder_id"] = strings.ToUpper(strings.TrimSpace(feeder))
	}
	txIDs := []string{}
	if selected, ok := resolution["selected_transformers"].([]any); ok {
		for _, raw := range selected {
			item, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			if id, ok := item["facility_id"].(string); ok && strings.TrimSpace(id) != "" {
				txIDs = append(txIDs, strings.ToUpper(strings.TrimSpace(id)))
			}
		}
	}
	result["transformer_ids"] = uniqueSortedStrings(txIDs)
	return result
}

func normalizeCorrelationPlannedState(value string) string {
	switch strings.ToUpper(strings.TrimSpace(value)) {
	case correlation.PlannedMatched:
		return correlation.PlannedMatched
	case correlation.PlannedNoMatch:
		return correlation.PlannedNoMatch
	case correlation.PlannedAmbiguous:
		return correlation.PlannedAmbiguous
	case correlation.PlannedUnavailable:
		return correlation.PlannedUnavailable
	case correlation.PlannedInconclusive:
		return correlation.PlannedInconclusive
	default:
		return correlation.PlannedNotChecked
	}
}

func uniqueSortedStrings(values []string) []string {
	set := map[string]struct{}{}
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" {
			set[value] = struct{}{}
		}
	}
	out := make([]string, 0, len(set))
	for value := range set {
		out = append(out, value)
	}
	for i := 0; i < len(out); i++ {
		for j := i + 1; j < len(out); j++ {
			if out[j] < out[i] {
				out[i], out[j] = out[j], out[i]
			}
		}
	}
	return out
}

func correlationEvidenceJSON(value any) json.RawMessage {
	return mustJSON(value)
}
