package api

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"

	"pea-api-intellisense/apps/api-go/internal/storage"
)

type correlationCaptureStore struct {
	*fakeStore
	accepted    []correlationCapturedRecord
	fail        bool
	snapshots   map[string]storage.CorrelationReportSnapshot
	jobs        map[string]storage.CorrelationJob
	memberships map[string]storage.CorrelationMembershipRevision
	clusters    map[string]storage.CorrelationClusterRevision
}

type correlationCapturedRecord struct {
	report   storage.CorrelationReport
	evidence storage.CorrelationEvidenceRevision
	job      storage.CorrelationJob
}

func newCorrelationCaptureStore() *correlationCaptureStore {
	return &correlationCaptureStore{
		fakeStore:   newFakeStore(),
		snapshots:   map[string]storage.CorrelationReportSnapshot{},
		jobs:        map[string]storage.CorrelationJob{},
		memberships: map[string]storage.CorrelationMembershipRevision{},
		clusters:    map[string]storage.CorrelationClusterRevision{},
	}
}

func (s *correlationCaptureStore) AcceptCorrelationReport(_ context.Context, report storage.CorrelationReport, evidence storage.CorrelationEvidenceRevision, job storage.CorrelationJob) (string, int, bool, error) {
	if s.fail {
		return "", 0, false, errors.New("synthetic correlation persistence failure")
	}
	s.accepted = append(s.accepted, correlationCapturedRecord{report: report, evidence: evidence, job: job})
	evidence.ReportID = report.ReportID
	evidence.Revision = 1
	job.ReportID = report.ReportID
	job.TriggerEvidenceRevision = 1
	s.snapshots[report.ReportID] = storage.CorrelationReportSnapshot{Report: report, Evidence: evidence}
	s.jobs[report.ReportID] = job
	return report.ReportID, 1, len(s.accepted) > 1, nil
}

func (s *correlationCaptureStore) GetCorrelationReportSnapshot(_ context.Context, reportID string) (*storage.CorrelationReportSnapshot, error) {
	item, ok := s.snapshots[reportID]
	if !ok {
		return nil, storage.ErrNotFound
	}
	copy := item
	return &copy, nil
}

func (s *correlationCaptureStore) GetLatestCorrelationJobForReport(_ context.Context, reportID string) (*storage.CorrelationJob, error) {
	item, ok := s.jobs[reportID]
	if !ok {
		return nil, storage.ErrNotFound
	}
	copy := item
	return &copy, nil
}

func (s *correlationCaptureStore) GetLatestCorrelationMembership(_ context.Context, reportID string) (*storage.CorrelationMembershipRevision, error) {
	item, ok := s.memberships[reportID]
	if !ok {
		return nil, storage.ErrNotFound
	}
	copy := item
	return &copy, nil
}

func (s *correlationCaptureStore) GetLatestCorrelationClusterRevision(_ context.Context, clusterID string) (*storage.CorrelationClusterRevision, error) {
	item, ok := s.clusters[clusterID]
	if !ok {
		return nil, storage.ErrNotFound
	}
	copy := item
	return &copy, nil
}

func TestCorrelationShadowQueuesOnlyAfterAcceptedReport(t *testing.T) {
	store := newCorrelationCaptureStore()
	h := NewServer(ServerConfig{
		OutageIntegrationAPIKey:        "n8n-key",
		IncidentCorrelationMode:        "shadow",
		IncidentCorrelationMaxAttempts: 5,
	}, store)
	body := chatbotTestBody("PEA-20260826-C0A101", "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "power_outage")
	res := callChatbotReport(t, h, body, "n8n-key")
	if res.Code != http.StatusCreated {
		t.Fatalf("expected accepted chatbot report, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["accept_status"] != "ACCEPTED" || payload["bot_action"] != "SHOW_ACK" {
		t.Fatalf("correlation shadow must not alter ACK semantics: %#v", payload)
	}
	if len(store.accepted) != 1 {
		t.Fatalf("expected one durable correlation capture, got %d", len(store.accepted))
	}
	captured := store.accepted[0]
	if captured.report.ReportID == "" || captured.report.TicketID != "PEA-20260826-C0A101" {
		t.Fatalf("invalid immutable correlation report identity: %#v", captured.report)
	}
	if captured.job.State != "PENDING" || captured.job.MaxAttempts != 5 || captured.job.TriggerKey == "" {
		t.Fatalf("expected durable pending correlation job: %#v", captured.job)
	}
	combined := string(captured.report.NormalizedLocationJSON) + string(captured.evidence.TopologyJSON) + string(captured.evidence.LocationJSON)
	for _, forbidden := range []string{"ผู้ใช้ทดสอบ", "0000000000"} {
		if strings.Contains(combined, forbidden) {
			t.Fatalf("correlation shadow must not persist customer PII %q: %s", forbidden, combined)
		}
	}
	if !strings.Contains(string(captured.evidence.TopologyJSON), "BUA03") {
		t.Fatalf("expected core topology context in evidence: %s", captured.evidence.TopologyJSON)
	}
}

func TestCorrelationShadowDoesNotQueueNeedsMoreInfo(t *testing.T) {
	store := newCorrelationCaptureStore()
	h := NewServer(ServerConfig{
		OutageIntegrationAPIKey: "n8n-key",
		IncidentCorrelationMode: "shadow",
	}, store)
	body := chatbotTestBody("PEA-20260826-C0A102", "บ้านนาโนน หมู่ 3", "บึงกาฬ", "บึงกาฬ", "นครพนม", "power_outage")
	res := callChatbotReport(t, h, body, "n8n-key")
	if res.Code != http.StatusOK {
		t.Fatalf("expected fail-closed clarification, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["accept_status"] != "NEEDS_MORE_INFO" {
		t.Fatalf("expected NEEDS_MORE_INFO, got %#v", payload)
	}
	if len(store.accepted) != 0 {
		t.Fatalf("preflight-incomplete report must not enter correlation, got %d captures", len(store.accepted))
	}
}

func TestCorrelationShadowPersistenceFailureNeverBreaksAck(t *testing.T) {
	store := newCorrelationCaptureStore()
	store.fail = true
	h := NewServer(ServerConfig{
		OutageIntegrationAPIKey: "n8n-key",
		IncidentCorrelationMode: "shadow",
	}, store)
	body := chatbotTestBody("PEA-20260826-C0A103", "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "power_outage")
	res := callChatbotReport(t, h, body, "n8n-key")
	if res.Code != http.StatusCreated {
		t.Fatalf("correlation failure must not break chatbot ACK, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["accept_status"] != "ACCEPTED" || payload["customer_message"].(map[string]any)["template_key"] != "ACK" {
		t.Fatalf("ACK semantics changed after correlation failure: %#v", payload)
	}
}
