package api

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"pea-api-intellisense/apps/api-go/internal/storage"
)

func TestPostAcceptsValidRequestAndKeepsProductionBlocked(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key", RateLimitPerMinute: 120}, store)
	body := `{"request_id":"AIS-HTTP-1","meter_no":"REDACTED-METER-0000","timestamp":"2026-06-19T17:04:00+07:00"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	req.Header.Set("X-Correlation-ID", "ais-corr-1")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["status"] != "RECEIVED" || payload["production_send"] != "blocked" {
		t.Fatalf("unsafe payload: %#v", payload)
	}
	if strings.Contains(res.Body.String(), "METER-1234") {
		t.Fatalf("response leaked raw meter: %s", res.Body.String())
	}
	if res.Header().Get("X-Correlation-ID") != "ais-corr-1" {
		t.Fatalf("correlation header was not preserved: %s", res.Header().Get("X-Correlation-ID"))
	}
}

func TestUnauthorizedRequestReturns401(t *testing.T) {
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(`{"request_id":"AIS-1"}`))
	req.Header.Set("Content-Type", "application/json")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", res.Code)
	}
	payload := decodeBody(t, res)
	if payload["production_send"] != "blocked" {
		t.Fatalf("production guardrail missing: %#v", payload)
	}
}

func TestDuplicateRequestIsIdempotent(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-DUP","meter_no":"REDACTED-METER-0000","timestamp":"2026-06-19T17:04:00+07:00"}`
	for idx := 0; idx < 2; idx++ {
		req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-API-Key", "pilot-key")
		res := httptest.NewRecorder()
		handler.ServeHTTP(res, req)
		payload := decodeBody(t, res)
		if idx == 1 && payload["duplicate"] != true {
			t.Fatalf("second request should be duplicate: %#v", payload)
		}
	}
	if store.inserted != 1 {
		t.Fatalf("expected one persisted request, got %d", store.inserted)
	}
}

func TestStatusLookupWorks(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-LOOKUP","meter_no":"REDACTED-METER-0000","timestamp":"2026-06-19T17:04:00+07:00"}`
	post := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	post.Header.Set("Content-Type", "application/json")
	post.Header.Set("X-API-Key", "pilot-key")
	handler.ServeHTTP(httptest.NewRecorder(), post)

	req := httptest.NewRequest(http.MethodGet, inboundPath+"/AIS-LOOKUP", nil)
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)

	if res.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["request_id"] != "AIS-LOOKUP" || payload["production_send"] != "blocked" {
		t.Fatalf("bad lookup payload: %#v", payload)
	}
}

func TestBadTimestampReturns400(t *testing.T) {
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	body := `{"request_id":"AIS-BAD","meter_no":"REDACTED-METER-0000","timestamp":"not-a-date"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", res.Code)
	}
	payload := decodeBody(t, res)
	if payload["production_send"] != "blocked" {
		t.Fatalf("production guardrail missing: %#v", payload)
	}
}

func TestLongOptionalFieldReturns400(t *testing.T) {
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	body := `{"request_id":"AIS-LONG","meter_no":"REDACTED-METER-0000","timestamp":"2026-06-19T17:04:00+07:00","province":"` + strings.Repeat("A", 121) + `"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", res.Code)
	}
	payload := decodeBody(t, res)
	if payload["production_send"] != "blocked" {
		t.Fatalf("production guardrail missing: %#v", payload)
	}
}

func TestMetricsEndpointIsAuthOnlyAndReportsShadowGuardrails(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-METRICS","meter_no":"REDACTED-METER-0000","timestamp":"2026-06-19T17:04:00+07:00"}`
	for idx := 0; idx < 2; idx++ {
		req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-API-Key", "pilot-key")
		handler.ServeHTTP(httptest.NewRecorder(), req)
	}

	unauth := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	unauthRes := httptest.NewRecorder()
	handler.ServeHTTP(unauthRes, unauth)
	if unauthRes.Code != http.StatusUnauthorized {
		t.Fatalf("expected auth on metrics, got %d", unauthRes.Code)
	}

	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)

	if res.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["production_send"] != "blocked" || payload["mode"] != "shadow" {
		t.Fatalf("unsafe metrics payload: %#v", payload)
	}
	if payload["total_requests"].(float64) != 1 || payload["duplicate_callbacks"].(float64) != 1 {
		t.Fatalf("bad metrics counts: %#v", payload)
	}
	if payload["pending_worker_traces"].(float64) != 1 || payload["not_ready_etr"].(float64) != 1 {
		t.Fatalf("worker handoff metrics missing: %#v", payload)
	}
}

func decodeBody(t *testing.T, res *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	payload := map[string]any{}
	if err := json.Unmarshal(res.Body.Bytes(), &payload); err != nil {
		t.Fatalf("bad json: %v", err)
	}
	return payload
}

type fakeStore struct {
	mu                 sync.Mutex
	rows               map[string]storage.RequestStatus
	callbackStatusCount map[string]int64
	inserted           int
}

func newFakeStore() *fakeStore {
	return &fakeStore{rows: map[string]storage.RequestStatus{}, callbackStatusCount: map[string]int64{}}
}

func (f *fakeStore) Init(context.Context) error { return nil }
func (f *fakeStore) Health(context.Context) error { return nil }
func (f *fakeStore) InsertCallback(ctx context.Context, callback storage.Callback) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.callbackStatusCount[callback.Status]++
	return nil
}
func (f *fakeStore) ListStatuses(ctx context.Context, limit int) ([]storage.RequestStatus, error) {
	return []storage.RequestStatus{}, nil
}

func (f *fakeStore) InsertInbound(ctx context.Context, request storage.InboundRequest, callback storage.Callback, evidence storage.EvidenceTrace, etr storage.ETRCandidate) (bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if _, ok := f.rows[request.RequestID]; ok {
		return true, nil
	}
	f.inserted++
	f.callbackStatusCount[callback.Status]++
	f.rows[request.RequestID] = storage.RequestStatus{
		RequestID:          request.RequestID,
		ReceivedAt:         request.ReceivedAt,
		DetectedAt:         request.DetectedAt,
		DetectedAtOriginal: request.DetectedAtOriginal,
		TimestampQuality:   request.TimestampQuality,
		MeterHash:          request.MeterHash,
		MeterLast4:         request.MeterLast4,
		Province:           request.Province,
		District:           request.District,
		Subdistrict:        request.Subdistrict,
		ResponseJSON:       request.ResponseJSON,
		RequestCallback:    request.CallbackStatus,
		CallbackPayload:    callback.PayloadJSON,
		LatestCallback:     callback.Status,
		EvidenceJSON:       evidence.EvidenceJSON,
		ETRStatus:          etr.Status,
		ProductionSend:     "blocked",
	}
	return false, nil
}

func (f *fakeStore) GetStatus(ctx context.Context, requestID string) (*storage.RequestStatus, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	row, ok := f.rows[requestID]
	if !ok {
		return nil, storage.ErrNotFound
	}
	return &row, nil
}

func (f *fakeStore) Metrics(ctx context.Context) (*storage.MetricsSnapshot, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	snapshot := &storage.MetricsSnapshot{CallbackCounts: map[string]int64{}}
	for status, count := range f.callbackStatusCount {
		snapshot.CallbackCounts[status] = count
		if status == "SKIPPED_DUPLICATE" {
			snapshot.DuplicateCallbacks = count
		}
	}
	for _, row := range f.rows {
		snapshot.TotalRequests++
		if row.LatestCallback != "" && snapshot.LatestReceivedAt == nil {
			receivedAt := row.ReceivedAt
			snapshot.LatestReceivedAt = &receivedAt
		}
		if row.ETRStatus == "NOT_READY_FOR_AUTO_SEND" {
			snapshot.NotReadyETR++
		}
		snapshot.PendingWorkerTraces++
	}
	return snapshot, nil
}
