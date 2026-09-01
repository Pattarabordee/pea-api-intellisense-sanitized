package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"pea-api-intellisense/apps/api-go/internal/storage"
)

type aggregateCorrelationStore struct {
	*correlationCaptureStore
}

func newAggregateCorrelationStore() *aggregateCorrelationStore {
	return &aggregateCorrelationStore{correlationCaptureStore: newCorrelationCaptureStore()}
}

func (s *aggregateCorrelationStore) ListCorrelationReportSnapshots(_ context.Context, limit int) ([]storage.CorrelationReportSnapshot, error) {
	result := make([]storage.CorrelationReportSnapshot, 0, len(s.snapshots))
	for _, item := range s.snapshots {
		result = append(result, item)
	}
	if limit > 0 && len(result) > limit {
		result = result[:limit]
	}
	return result, nil
}

func (s *aggregateCorrelationStore) ListLatestCorrelationMemberships(_ context.Context) ([]storage.CorrelationMembershipRevision, error) {
	result := make([]storage.CorrelationMembershipRevision, 0, len(s.memberships))
	for _, item := range s.memberships {
		result = append(result, item)
	}
	return result, nil
}

func callCorrelationAggregate(t *testing.T, h http.Handler, key string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, correlationAggregatePath, nil)
	if key != "" {
		req.Header.Set("X-API-Key", key)
	}
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	return res
}

func aggregateSnapshot(reportID, ticketID, province, district, feeder string, transformers []string, occurredAt time.Time) storage.CorrelationReportSnapshot {
	location := mustJSON(map[string]any{
		"province": province,
		"district": district,
	})
	topology := mustJSON(map[string]any{
		"feeder_id": feeder,
		"transformer_ids": transformers,
		"authoritative": true,
	})
	return storage.CorrelationReportSnapshot{
		Report: storage.CorrelationReport{
			ReportID: reportID,
			TicketID: ticketID,
			SourceSystem: "n8n-pea-buengkan",
			SourceChannel: "n8n",
			OccurredAt: occurredAt,
			NormalizedLocationJSON: location,
			Mode: "shadow",
			ProductionSend: "blocked",
			CreatedAt: occurredAt,
		},
		Evidence: storage.CorrelationEvidenceRevision{
			ReportID: reportID,
			Revision: 1,
			TopologyJSON: topology,
			LocationJSON: location,
			EvidenceQuality: "CORE_TOPOLOGY_PROVISIONAL_FRESHNESS",
			RecordedAt: occurredAt,
			SourceVersion: "incident-correlation-shadow-v1.0.0",
		},
	}
}

func TestCorrelationAggregateRequiresIntegrationAuth(t *testing.T) {
	store := newAggregateCorrelationStore()
	h := NewServer(ServerConfig{OutageIntegrationAPIKey: "n8n-key", IncidentCorrelationMode: "shadow"}, store)
	res := callCorrelationAggregate(t, h, "")
	if res.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d: %s", res.Code, res.Body.String())
	}
}

func TestCorrelationAggregateFailsClosedWhenCorrelationNotShadow(t *testing.T) {
	store := newAggregateCorrelationStore()
	h := NewServer(ServerConfig{OutageIntegrationAPIKey: "n8n-key", IncidentCorrelationMode: "off"}, store)
	res := callCorrelationAggregate(t, h, "n8n-key")
	if res.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["production_send"] != "blocked" || payload["authoritative_outage_truth"] != false {
		t.Fatalf("unsafe disabled payload: %#v", payload)
	}
}

func TestCorrelationAggregateEmitsPrivacySafeIncidentProjection(t *testing.T) {
	store := newAggregateCorrelationStore()
	clusterID := "cluster_internal_secret_must_not_leak"
	base := time.Date(2026, 9, 1, 9, 0, 0, 0, time.UTC)
	store.snapshots["report-a"] = aggregateSnapshot("report-a", "PEA-20260901-AAAAAA", "บึงกาฬ", "เมืองบึงกาฬ", "BUA03", []string{"63-006344"}, base)
	store.snapshots["report-b"] = aggregateSnapshot("report-b", "PEA-20260901-BBBBBB", "บึงกาฬ", "เมืองบึงกาฬ", "BUA03", []string{"63-006344"}, base.Add(2*time.Minute))
	store.memberships["report-a"] = storage.CorrelationMembershipRevision{ReportID: "report-a", ClusterID: clusterID, MembershipState: "ACTIVE"}
	store.memberships["report-b"] = storage.CorrelationMembershipRevision{ReportID: "report-b", ClusterID: clusterID, MembershipState: "ACTIVE"}
	store.clusters[clusterID] = storage.CorrelationClusterRevision{
		ClusterID: clusterID,
		Revision: 2,
		LifecycleState: "ACTIVE",
		CorrelationStatus: "SUSPECTED_RELATED",
		ConfidenceScore: 0.91,
		ConfidenceLevel: "HIGH",
		RawReportCount: 2,
		UniqueReporterCount: 2,
		EngineVersion: "incident-correlation-shadow-v1.0.0",
	}

	h := NewServer(ServerConfig{OutageIntegrationAPIKey: "n8n-key", IncidentCorrelationMode: "shadow"}, store)
	res := callCorrelationAggregate(t, h, "n8n-key")
	if res.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["schema_version"] != correlationAggregateSchema || payload["mode"] != "shadow" || payload["production_send"] != "blocked" {
		t.Fatalf("bad aggregate envelope: %#v", payload)
	}
	items := payload["items"].([]any)
	if len(items) != 1 {
		t.Fatalf("expected one aggregate incident, got %#v", payload)
	}
	item := items[0].(map[string]any)
	if item["area"] != "BKN" || item["transformer_id"] != "63-006344" || item["feeder_id"] != "BUA03" {
		t.Fatalf("bad area/topology projection: %#v", item)
	}
	if item["affected_customers"] != nil || item["critical_customer_risk"] != "NOT_EVALUATED" {
		t.Fatalf("aggregate must not invent affected-customer/critical-risk facts: %#v", item)
	}
	if item["report_count"].(float64) != 2 || item["evidence_strength"] != "STRONG" {
		t.Fatalf("bad report/evidence projection: %#v", item)
	}
	if item["operational_incident_confirmed"] != false || item["root_cause_confirmed"] != false || item["authoritative_outage_truth"] != false {
		t.Fatalf("aggregate must remain non-authoritative: %#v", item)
	}
	if strings.Contains(res.Body.String(), clusterID) || strings.Contains(res.Body.String(), "PEA-20260901-AAAAAA") {
		t.Fatalf("raw cluster/ticket identifier leaked: %s", res.Body.String())
	}
	if _, exists := item["confidence_score"]; exists {
		t.Fatalf("numeric correlation score must not be exposed: %#v", item)
	}
}

func TestCorrelationAggregatePreservesAmbiguousTopologyAsNull(t *testing.T) {
	store := newAggregateCorrelationStore()
	clusterID := "cluster-ambiguous"
	base := time.Date(2026, 9, 1, 10, 0, 0, 0, time.UTC)
	store.snapshots["report-a"] = aggregateSnapshot("report-a", "PEA-20260901-CCCCCC", "บึงกาฬ", "เมืองบึงกาฬ", "BUA03", []string{"63-006344"}, base)
	store.snapshots["report-b"] = aggregateSnapshot("report-b", "PEA-20260901-DDDDDD", "บึงกาฬ", "เมืองบึงกาฬ", "BUA03", []string{"64-016689"}, base.Add(time.Minute))
	store.memberships["report-a"] = storage.CorrelationMembershipRevision{ReportID: "report-a", ClusterID: clusterID, MembershipState: "ACTIVE"}
	store.memberships["report-b"] = storage.CorrelationMembershipRevision{ReportID: "report-b", ClusterID: clusterID, MembershipState: "ACTIVE"}
	store.clusters[clusterID] = storage.CorrelationClusterRevision{ClusterID: clusterID, LifecycleState: "ACTIVE", CorrelationStatus: "SUSPECTED_RELATED", ConfidenceLevel: "MEDIUM", RawReportCount: 2}

	h := NewServer(ServerConfig{OutageIntegrationAPIKey: "n8n-key", IncidentCorrelationMode: "shadow"}, store)
	res := callCorrelationAggregate(t, h, "n8n-key")
	payload := decodeBody(t, res)
	item := payload["items"].([]any)[0].(map[string]any)
	if item["transformer_id"] != nil || item["topology_state"] != "AMBIGUOUS_TRANSFORMER" {
		t.Fatalf("ambiguous topology must remain unresolved: %#v", item)
	}
}

func TestCorrelationAggregateOmitsUnknownAreaInsteadOfGuessing(t *testing.T) {
	store := newAggregateCorrelationStore()
	clusterID := "cluster-unknown-area"
	base := time.Date(2026, 9, 1, 11, 0, 0, 0, time.UTC)
	store.snapshots["report-a"] = aggregateSnapshot("report-a", "PEA-20260901-EEEEEE", "UNKNOWN", "UNKNOWN", "ZZZ01", []string{"TX-1"}, base)
	store.memberships["report-a"] = storage.CorrelationMembershipRevision{ReportID: "report-a", ClusterID: clusterID, MembershipState: "ACTIVE"}
	store.clusters[clusterID] = storage.CorrelationClusterRevision{ClusterID: clusterID, LifecycleState: "ACTIVE", CorrelationStatus: "SUSPECTED_RELATED", ConfidenceLevel: "LOW", RawReportCount: 1}

	h := NewServer(ServerConfig{OutageIntegrationAPIKey: "n8n-key", IncidentCorrelationMode: "shadow"}, store)
	res := callCorrelationAggregate(t, h, "n8n-key")
	payload := decodeBody(t, res)
	if len(payload["items"].([]any)) != 0 {
		t.Fatalf("unknown service area must not be guessed: %#v", payload)
	}
	health := payload["projection_health"].(map[string]any)
	if health["unknown_area_omitted_count"].(float64) != 1 {
		t.Fatalf("expected explicit unknown-area omission count: %#v", health)
	}
}

func TestServiceAreaFromLocationSupportsPhangKhonWithoutAssumingAllSakonNakhon(t *testing.T) {
	pkn := serviceAreaFromLocation(json.RawMessage(`{"province":"สกลนคร","district":"พังโคน"}`))
	if pkn != "PKN" {
		t.Fatalf("expected PKN, got %q", pkn)
	}
	other := serviceAreaFromLocation(json.RawMessage(`{"province":"สกลนคร","district":"เมืองสกลนคร"}`))
	if other != "" {
		t.Fatalf("must not map all Sakon Nakhon to PKN, got %q", other)
	}
}
