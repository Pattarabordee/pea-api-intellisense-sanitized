package api

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"pea-api-intellisense/apps/api-go/internal/storage"
)

const (
	correlationAggregatePath   = "/api/v1/incidents/correlation-aggregate"
	correlationAggregateSchema = "pea-incident-aggregate-source.v0.1"
)

type correlationAggregateStore interface {
	ListCorrelationReportSnapshots(context.Context, int) ([]storage.CorrelationReportSnapshot, error)
	ListLatestCorrelationMemberships(context.Context) ([]storage.CorrelationMembershipRevision, error)
	GetLatestCorrelationClusterRevision(context.Context, string) (*storage.CorrelationClusterRevision, error)
}

type aggregateIncidentGroup struct {
	clusterID string
	reports   []storage.CorrelationReportSnapshot
	cluster   storage.CorrelationClusterRevision
}

func (s *Server) handleCorrelationAggregate(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	if normalizeIncidentCorrelationMode(s.cfg.IncidentCorrelationMode) != "shadow" {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"schema_version":             correlationAggregateSchema,
			"mode":                       "shadow",
			"production_send":            ProductionSend,
			"authoritative_outage_truth": false,
			"status":                     "UNAVAILABLE",
			"error_code":                 "INCIDENT_CORRELATION_NOT_IN_SHADOW_MODE",
			"items":                      []any{},
			"generated_at":               nowISO(),
		})
		return
	}
	store, ok := s.store.(correlationAggregateStore)
	if !ok {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"schema_version":             correlationAggregateSchema,
			"mode":                       "shadow",
			"production_send":            ProductionSend,
			"authoritative_outage_truth": false,
			"status":                     "UNAVAILABLE",
			"error_code":                 "CORRELATION_AGGREGATE_STORE_UNAVAILABLE",
			"items":                      []any{},
			"generated_at":               nowISO(),
		})
		return
	}

	limit := aggregateLimit(r.URL.Query().Get("limit"))
	items, health, err := buildCorrelationAggregate(r.Context(), store, limit, time.Now().UTC())
	if err != nil {
		s.cfg.Logger.Error("correlation aggregate read failed", "error", err)
		writeJSON(w, http.StatusInternalServerError, map[string]any{
			"schema_version":             correlationAggregateSchema,
			"mode":                       "shadow",
			"production_send":            ProductionSend,
			"authoritative_outage_truth": false,
			"status":                     "UNAVAILABLE",
			"error_code":                 "CORRELATION_AGGREGATE_READ_FAILED",
			"items":                      []any{},
			"generated_at":               nowISO(),
		})
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"schema_version":             correlationAggregateSchema,
		"mode":                       "shadow",
		"production_send":            ProductionSend,
		"authoritative_outage_truth": false,
		"source_id":                  "pea-intellisense:incident-correlation-shadow",
		"generated_at":               nowISO(),
		"count":                      len(items),
		"projection_health":          health,
		"items":                      items,
	})
}

func aggregateLimit(raw string) int {
	value, err := strconv.Atoi(strings.TrimSpace(raw))
	if err != nil || value <= 0 {
		return 250
	}
	if value > 250 {
		return 250
	}
	return value
}

func buildCorrelationAggregate(ctx context.Context, store correlationAggregateStore, limit int, now time.Time) ([]map[string]any, map[string]any, error) {
	// Read enough recent report snapshots to build up to the requested incident limit.
	// The source remains a projection of durable backend-owned state; it never mutates correlation state.
	snapshots, err := store.ListCorrelationReportSnapshots(ctx, 2000)
	if err != nil {
		return nil, nil, err
	}
	memberships, err := store.ListLatestCorrelationMemberships(ctx)
	if err != nil {
		return nil, nil, err
	}

	membershipByReport := make(map[string]storage.CorrelationMembershipRevision, len(memberships))
	for _, membership := range memberships {
		membershipByReport[membership.ReportID] = membership
	}

	reportsByCluster := map[string][]storage.CorrelationReportSnapshot{}
	activeMemberships := 0
	for _, snapshot := range snapshots {
		membership, ok := membershipByReport[snapshot.Report.ReportID]
		if !ok || strings.ToUpper(strings.TrimSpace(membership.MembershipState)) != "ACTIVE" || strings.TrimSpace(membership.ClusterID) == "" {
			continue
		}
		activeMemberships++
		reportsByCluster[membership.ClusterID] = append(reportsByCluster[membership.ClusterID], snapshot)
	}

	groups := make([]aggregateIncidentGroup, 0, len(reportsByCluster))
	missingClusterRevision := 0
	inactiveCluster := 0
	for clusterID, reports := range reportsByCluster {
		cluster, err := store.GetLatestCorrelationClusterRevision(ctx, clusterID)
		if err != nil {
			if err == storage.ErrNotFound {
				missingClusterRevision++
				continue
			}
			return nil, nil, err
		}
		if strings.ToUpper(strings.TrimSpace(cluster.LifecycleState)) != "ACTIVE" {
			inactiveCluster++
			continue
		}
		groups = append(groups, aggregateIncidentGroup{clusterID: clusterID, reports: reports, cluster: *cluster})
	}

	sort.Slice(groups, func(i, j int) bool {
		return firstReportedAt(groups[i].reports).After(firstReportedAt(groups[j].reports))
	})

	items := make([]map[string]any, 0, minInt(limit, len(groups)))
	unknownArea := 0
	ambiguousArea := 0
	for _, group := range groups {
		if len(items) >= limit {
			break
		}
		area, areaLabel, state := strictServiceArea(group.reports)
		switch state {
		case "UNKNOWN":
			unknownArea++
			continue
		case "AMBIGUOUS":
			ambiguousArea++
			continue
		}
		items = append(items, aggregateIncidentItem(group, area, areaLabel, now))
	}

	health := map[string]any{
		"snapshot_count":                  len(snapshots),
		"active_membership_count":         activeMemberships,
		"active_cluster_candidate_count":  len(groups),
		"missing_cluster_revision_count":  missingClusterRevision,
		"inactive_cluster_count":          inactiveCluster,
		"unknown_area_omitted_count":      unknownArea,
		"ambiguous_area_omitted_count":    ambiguousArea,
		"emitted_incident_count":          len(items),
		"affected_customer_count_source":  "NOT_AVAILABLE_IN_CORRELATION_V1",
		"critical_customer_risk_source":   "NOT_EVALUATED_IN_CORRELATION_V1",
		"priority_semantics_included":      false,
		"operational_incident_confirmed":  false,
		"root_cause_confirmed":            false,
		"customer_truth_changed":          false,
	}
	return items, health, nil
}

func aggregateIncidentItem(group aggregateIncidentGroup, area, areaLabel string, now time.Time) map[string]any {
	first := firstReportedAt(group.reports)
	waiting := int(now.Sub(first).Minutes())
	if waiting < 0 {
		waiting = 0
	}
	transformerID, feederID, topologyState := uniqueTopology(group.reports)
	confidence := strings.ToUpper(strings.TrimSpace(group.cluster.ConfidenceLevel))
	if confidence == "" {
		confidence = "UNKNOWN"
	}
	correlationState := strings.ToUpper(strings.TrimSpace(group.cluster.CorrelationStatus))
	if correlationState == "" {
		correlationState = "SUSPECTED_RELATED"
	}

	reportCount := group.cluster.RawReportCount
	if reportCount <= 0 {
		reportCount = len(group.reports)
	}
	uniqueReporters := group.cluster.UniqueReporterCount
	if uniqueReporters < 0 {
		uniqueReporters = 0
	}

	reasons := []string{
		fmt.Sprintf("Incident Correlation state %s", correlationState),
		fmt.Sprintf("%d accepted report(s) in cluster", reportCount),
		fmt.Sprintf("Correlation confidence %s", confidence),
		fmt.Sprintf("Topology state %s", topologyState),
	}
	evidenceChain := []string{
		"Accepted outage reports",
		"Incident Correlation shadow",
		"PEA topology evidence",
	}
	if transformerID != nil {
		evidenceChain = append(evidenceChain, "Unique transformer evidence")
	} else {
		evidenceChain = append(evidenceChain, "Transformer unresolved/ambiguous")
	}

	return map[string]any{
		"incident_id":                    hashReference("correlation_cluster", group.clusterID),
		"area":                           area,
		"area_label":                     areaLabel,
		"transformer_id":                 transformerID,
		"feeder_id":                      feederID,
		"affected_customers":             nil,
		"report_count":                   reportCount,
		"unique_reporter_count":          uniqueReporters,
		"critical_customer_risk":         "NOT_EVALUATED",
		"evidence_strength":              correlationEvidenceStrength(confidence),
		"correlation_confidence_level":   confidence,
		"correlation_state":              correlationState,
		"topology_state":                 topologyState,
		"first_reported_at":              first.Format(time.RFC3339),
		"waiting_minutes":                waiting,
		"status":                         "NEW",
		"event_type":                     correlationState,
		"ai_summary":                     fmt.Sprintf("Shadow correlation groups %d accepted report(s) with %s confidence; outage truth, root cause, affected-customer count and critical-customer risk remain unconfirmed.", reportCount, confidence),
		"priority_reasons":               reasons,
		"evidence_chain":                 evidenceChain,
		"authoritative_outage_truth":     false,
		"operational_incident_confirmed": false,
		"root_cause_confirmed":           false,
	}
}

func firstReportedAt(reports []storage.CorrelationReportSnapshot) time.Time {
	var first time.Time
	for _, report := range reports {
		candidate := report.Report.OccurredAt
		if candidate.IsZero() {
			candidate = report.Report.CreatedAt
		}
		if first.IsZero() || candidate.Before(first) {
			first = candidate
		}
	}
	if first.IsZero() {
		return time.Unix(0, 0).UTC()
	}
	return first.UTC()
}

func strictServiceArea(reports []storage.CorrelationReportSnapshot) (string, string, string) {
	areas := map[string]struct{}{}
	for _, report := range reports {
		area := serviceAreaFromLocation(report.Evidence.LocationJSON)
		if area == "" {
			area = serviceAreaFromLocation(report.Report.NormalizedLocationJSON)
		}
		if area == "" {
			return "", "", "UNKNOWN"
		}
		areas[area] = struct{}{}
	}
	if len(areas) != 1 {
		return "", "", "AMBIGUOUS"
	}
	for area := range areas {
		if area == "BKN" {
			return "BKN", "บึงกาฬ", "OK"
		}
		if area == "PKN" {
			return "PKN", "พังโคน", "OK"
		}
	}
	return "", "", "UNKNOWN"
}

func serviceAreaFromLocation(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	var location map[string]any
	if json.Unmarshal(raw, &location) != nil {
		return ""
	}
	province := normalizeAreaText(fmt.Sprint(location["province"]))
	district := normalizeAreaText(fmt.Sprint(location["district"]))
	if province == "บึงกาฬ" || province == "bueng kan" || province == "buengkan" {
		return "BKN"
	}
	if district == "พังโคน" || district == "phang khon" || district == "phangkhon" {
		return "PKN"
	}
	return ""
}

func normalizeAreaText(value string) string {
	return strings.ToLower(strings.Join(strings.Fields(strings.TrimSpace(value)), " "))
}

func uniqueTopology(reports []storage.CorrelationReportSnapshot) (any, any, string) {
	transformers := map[string]struct{}{}
	feeders := map[string]struct{}{}
	for _, report := range reports {
		var topology map[string]any
		if json.Unmarshal(report.Evidence.TopologyJSON, &topology) != nil {
			continue
		}
		if feeder, ok := topology["feeder_id"].(string); ok {
			feeder = strings.ToUpper(strings.TrimSpace(feeder))
			if feeder != "" {
				feeders[feeder] = struct{}{}
			}
		}
		switch values := topology["transformer_ids"].(type) {
		case []any:
			for _, raw := range values {
				if value, ok := raw.(string); ok {
					value = strings.ToUpper(strings.TrimSpace(value))
					if value != "" {
						transformers[value] = struct{}{}
					}
				}
			}
		case []string:
			for _, value := range values {
				value = strings.ToUpper(strings.TrimSpace(value))
				if value != "" {
					transformers[value] = struct{}{}
				}
			}
		}
	}

	var transformer any
	var feeder any
	if len(transformers) == 1 {
		for value := range transformers {
			transformer = value
		}
	}
	if len(feeders) == 1 {
		for value := range feeders {
			feeder = value
		}
	}

	state := "TRANSFORMER_UNRESOLVED"
	if len(transformers) == 1 {
		state = "UNIQUE_TRANSFORMER"
	} else if len(transformers) > 1 {
		state = "AMBIGUOUS_TRANSFORMER"
	}
	return transformer, feeder, state
}

func correlationEvidenceStrength(confidence string) string {
	switch strings.ToUpper(strings.TrimSpace(confidence)) {
	case "HIGH":
		return "STRONG"
	case "MEDIUM":
		return "MODERATE"
	default:
		return "LIMITED"
	}
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
