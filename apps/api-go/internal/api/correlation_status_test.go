package api

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"pea-api-intellisense/apps/api-go/internal/storage"
)

func callChatbotCorrelation(t *testing.T, h http.Handler, ticketID, key string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, chatbotReportsPath+"/"+ticketID+"/correlation", nil)
	if key != "" {
		req.Header.Set("X-API-Key", key)
	}
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	return res
}

func acceptedCorrelationFixture(t *testing.T, ticketID string) (*correlationCaptureStore, http.Handler, string) {
	t.Helper()
	store := newCorrelationCaptureStore()
	h := NewServer(ServerConfig{
		OutageIntegrationAPIKey:        "n8n-key",
		IncidentCorrelationMode:        "shadow",
		IncidentCorrelationMaxAttempts: 5,
	}, store)
	body := chatbotTestBody(ticketID, "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "power_outage")
	res := callChatbotReport(t, h, body, "n8n-key")
	if res.Code != http.StatusCreated {
		t.Fatalf("expected accepted fixture, got %d: %s", res.Code, res.Body.String())
	}
	if len(store.accepted) != 1 {
		t.Fatalf("expected one correlation capture, got %d", len(store.accepted))
	}
	return store, h, store.accepted[0].report.ReportID
}

func TestChatbotCorrelationStatusRequiresIntegrationAuth(t *testing.T) {
	store := newCorrelationCaptureStore()
	h := NewServer(ServerConfig{OutageIntegrationAPIKey: "n8n-key", IncidentCorrelationMode: "shadow"}, store)
	res := callChatbotCorrelation(t, h, "PEA-20260826-C0B100", "")
	if res.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d: %s", res.Code, res.Body.String())
	}
}

func TestChatbotCorrelationStatusUnknownTicketIsSafeNotFound(t *testing.T) {
	store := newCorrelationCaptureStore()
	h := NewServer(ServerConfig{OutageIntegrationAPIKey: "n8n-key", IncidentCorrelationMode: "shadow"}, store)
	res := callChatbotCorrelation(t, h, "PEA-20260826-C0B101", "n8n-key")
	if res.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["found"] != false || payload["bot_action"] != "NO_CUSTOMER_ACTION" {
		t.Fatalf("unsafe not-found semantics: %#v", payload)
	}
	corr := payload["correlation"].(map[string]any)
	if corr["state"] != "NOT_FOUND" || payload["production_send"] != "blocked" {
		t.Fatalf("bad not-found payload: %#v", payload)
	}
}

func TestChatbotCorrelationStatusPendingDoesNotChangeCustomerTruth(t *testing.T) {
	_, h, _ := acceptedCorrelationFixture(t, "PEA-20260826-C0B102")
	res := callChatbotCorrelation(t, h, "PEA-20260826-C0B102", "n8n-key")
	if res.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	corr := payload["correlation"].(map[string]any)
	if corr["state"] != "PENDING" || corr["available"] != true {
		t.Fatalf("expected pending correlation, got %#v", payload)
	}
	if payload["bot_action"] != "NO_CUSTOMER_ACTION" || payload["customer_truth_changed"] != false || payload["production_send"] != "blocked" {
		t.Fatalf("correlation GET must stay shadow/read-only: %#v", payload)
	}
}

func TestChatbotCorrelationStatusSucceededWithoutClusterIsNoCluster(t *testing.T) {
	store, h, reportID := acceptedCorrelationFixture(t, "PEA-20260826-C0B103")
	job := store.jobs[reportID]
	job.State = "SUCCEEDED"
	store.jobs[reportID] = job

	res := callChatbotCorrelation(t, h, "PEA-20260826-C0B103", "n8n-key")
	payload := decodeBody(t, res)
	corr := payload["correlation"].(map[string]any)
	if corr["state"] != "NO_CLUSTER" || corr["cluster_ref"] != "" {
		t.Fatalf("expected completed singleton/no-cluster state: %#v", payload)
	}
}

func TestChatbotCorrelationStatusReturnsSafeSuspectedClusterSummary(t *testing.T) {
	store, h, reportID := acceptedCorrelationFixture(t, "PEA-20260826-C0B104")
	job := store.jobs[reportID]
	job.State = "SUCCEEDED"
	store.jobs[reportID] = job
	clusterID := "clu_internal_identifier_must_not_leak"
	store.memberships[reportID] = storage.CorrelationMembershipRevision{
		ReportID: reportID, ClusterID: clusterID, MembershipRevision: 1, MembershipState: "ACTIVE",
		ConfidenceLevel: "HIGH", EngineVersion: "incident-correlation-shadow-v1",
	}
	store.clusters[clusterID] = storage.CorrelationClusterRevision{
		ClusterID: clusterID, Revision: 3, LifecycleState: "ACTIVE", CorrelationStatus: "SUSPECTED_RELATED",
		ConfidenceLevel: "HIGH", RawReportCount: 3, UniqueReporterCount: 2, EngineVersion: "incident-correlation-shadow-v1",
	}

	res := callChatbotCorrelation(t, h, "PEA-20260826-C0B104", "n8n-key")
	payload := decodeBody(t, res)
	corr := payload["correlation"].(map[string]any)
	if corr["state"] != "SUSPECTED_RELATED" || corr["confidence_level"] != "HIGH" || corr["report_count"].(float64) != 3 {
		t.Fatalf("bad suspected cluster summary: %#v", payload)
	}
	if corr["cluster_ref"] == "" || corr["cluster_ref"] == clusterID || strings.Contains(res.Body.String(), clusterID) {
		t.Fatalf("raw internal cluster id leaked: %s", res.Body.String())
	}
	if _, exists := corr["confidence_score"]; exists {
		t.Fatalf("n8n-safe correlation response must not expose numeric score: %#v", corr)
	}
	if payload["operational_incident_confirmed"] != false || payload["root_cause_confirmed"] != false {
		t.Fatalf("correlation must not confirm incident/root cause: %#v", payload)
	}
}

func TestChatbotCorrelationStatusFailedWorkerIsUnavailableNotOutageFailure(t *testing.T) {
	store, h, reportID := acceptedCorrelationFixture(t, "PEA-20260826-C0B105")
	job := store.jobs[reportID]
	job.State = "FAILED"
	store.jobs[reportID] = job

	res := callChatbotCorrelation(t, h, "PEA-20260826-C0B105", "n8n-key")
	payload := decodeBody(t, res)
	corr := payload["correlation"].(map[string]any)
	if corr["state"] != "UNAVAILABLE" || corr["reason_code"] != "CORRELATION_PROCESSING_FAILED" {
		t.Fatalf("expected fail-closed correlation unavailability: %#v", payload)
	}
	if payload["found"] != true || payload["customer_truth_changed"] != false {
		t.Fatalf("worker failure must not rewrite accepted outage receipt: %#v", payload)
	}
}

func TestChatbotCorrelationStatusPlannedOutageUsesSeparateSafeLane(t *testing.T) {
	store, h, reportID := acceptedCorrelationFixture(t, "PEA-20260826-C0B106")
	job := store.jobs[reportID]
	job.State = "SUCCEEDED"
	store.jobs[reportID] = job
	snapshot := store.snapshots[reportID]
	snapshot.Evidence.PlannedOutageState = "PLANNED_OUTAGE_MATCHED"
	store.snapshots[reportID] = snapshot

	res := callChatbotCorrelation(t, h, "PEA-20260826-C0B106", "n8n-key")
	payload := decodeBody(t, res)
	corr := payload["correlation"].(map[string]any)
	if corr["state"] != "PLANNED_OUTAGE_LINKED" {
		t.Fatalf("expected separate planned-outage lane: %#v", payload)
	}
	if payload["bot_action"] != "NO_CUSTOMER_ACTION" || payload["operational_incident_confirmed"] != false {
		t.Fatalf("planned outage linkage must not become automatic customer/incident truth: %#v", payload)
	}
}

func TestChatbotCorrelationStatusCoreAcceptedButCapabilityUnavailableFailsClosed(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{
		OutageIntegrationAPIKey: "n8n-key",
		IncidentCorrelationMode: "off",
	}, store)
	body := chatbotTestBody("PEA-20260826-C0B107", "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "power_outage")
	post := callChatbotReport(t, h, body, "n8n-key")
	if post.Code != http.StatusCreated {
		t.Fatalf("expected accepted core report, got %d: %s", post.Code, post.Body.String())
	}

	res := callChatbotCorrelation(t, h, "PEA-20260826-C0B107", "n8n-key")
	payload := decodeBody(t, res)
	corr := payload["correlation"].(map[string]any)
	if corr["state"] != "UNAVAILABLE" || corr["reason_code"] != "CORRELATION_STORE_UNAVAILABLE" {
		t.Fatalf("expected safe capability unavailability: %#v", payload)
	}
	if payload["found"] != true || payload["customer_truth_changed"] != false || payload["production_send"] != "blocked" {
		t.Fatalf("capability gap must not rewrite accepted core truth: %#v", payload)
	}
}
