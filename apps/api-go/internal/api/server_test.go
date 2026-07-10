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
	"time"

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

func TestPostCapturesAISTruthObservationWithoutLeakingSiteOrMeter(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key", RateLimitPerMinute: 120}, store)
	body := `{"request_id":"AIS-TRUTH-1","source_event_id":"SRC-1001","event_type":"OUTAGE","site_id":"SITE-SECRET-99","meter_no":"METER-1234","timestamp":"2026-06-19T17:04:00+07:00","outage_at":"2026-06-19T17:04:00+07:00"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d: %s", res.Code, res.Body.String())
	}
	row := store.rows["AIS-TRUTH-1"]
	if row.TruthEventType != "OUTAGE" || row.TruthValidation != "READY_FOR_LEDGER" {
		t.Fatalf("truth observation was not stored as ready outage: %#v", row)
	}
	if row.TruthSiteHash == "" || row.TruthSiteLast4 != "T-99" {
		t.Fatalf("site reference was not redacted into hash/last4: %#v", row)
	}
	if strings.Contains(res.Body.String(), "METER-1234") || strings.Contains(res.Body.String(), "SITE-SECRET-99") {
		t.Fatalf("response leaked raw identifiers: %s", res.Body.String())
	}
}

func TestPostWithoutSourceOrSiteUsesMeterStateTruth(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-LEGACY-1","event_type":"OUTAGE","meter_no":"METER-1234","timestamp":"2026-06-19T17:04:00+07:00","outage_at":"2026-06-19T17:04:00+07:00"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d: %s", res.Code, res.Body.String())
	}
	if got := store.rows["AIS-LEGACY-1"].TruthValidation; got != "READY_FOR_LEDGER" {
		t.Fatalf("meter-state truth must not require source or site ids, got %q", got)
	}
}

func TestPostUsesRequestTimestampAsEventTimestamp(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-MISSING-OUTAGE-TIME","source_event_id":"SRC-2001","event_type":"OUTAGE","meter_no":"METER-1234","timestamp":"2026-06-19T17:04:00+07:00"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d: %s", res.Code, res.Body.String())
	}
	if got := store.rows["AIS-MISSING-OUTAGE-TIME"].TruthValidation; got != "READY_FOR_LEDGER" {
		t.Fatalf("explicit outage must use request timestamp when outage_at is absent, got %q", got)
	}
}

func TestCauseTextDoesNotCreateModelTruth(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-CAUSE-ONLY","meter_no":"METER-1234","timestamp":"2026-06-19T17:04:00+07:00","alarm_type":"UNCLASSIFIED_ALARM","main_cause":"power failure"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)
	row := store.rows["AIS-CAUSE-ONLY"]
	if row.TruthEventType != "STATUS" || row.TruthEventTypeSource != "mapped_unknown" || row.TruthValidation != "REVIEW_EVENT_TYPE" {
		t.Fatalf("cause text must not create model truth: %#v", row)
	}
}

func TestACMainFailAlarmCreatesMappedOutage(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-ALARM-OUTAGE","meter_no":"METER-1234","timestamp":"2026-06-19T17:04:00+07:00","alarm_type":"AC_MAIN_FAIL"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)
	row := store.rows["AIS-ALARM-OUTAGE"]
	if row.TruthEventType != "OUTAGE" || row.TruthEventTypeSource != "mapped_alarm_type" || row.TruthValidation != "READY_FOR_LEDGER" {
		t.Fatalf("AC_MAIN_FAIL must create an allowlisted mapped outage: %#v", row)
	}
}

func TestACMainRestoreRemainsReviewBeforeContractGate(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-ALARM-RESTORE-CANDIDATE","meter_no":"METER-1234","timestamp":"2026-07-10T17:30:00+07:00","alarm_type":"AC_MAIN_RESTORE"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)
	row := store.rows["AIS-ALARM-RESTORE-CANDIDATE"]
	if row.TruthEventType != "STATUS" || row.TruthEventTypeSource != "mapped_unknown" || row.TruthValidation != "REVIEW_EVENT_TYPE" {
		t.Fatalf("restore alarm must remain review-only before contract activation: %#v", row)
	}
}

func TestMappedPowerStatusCreatesMeterStateTruth(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-MAPPED-OUTAGE","meter_no":"METER-1234","timestamp":"2026-06-19T17:04:00+07:00","power_status":"OFF"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)
	row := store.rows["AIS-MAPPED-OUTAGE"]
	if row.TruthEventType != "OUTAGE" || row.TruthEventTypeSource != "mapped_status" || row.TruthValidation != "READY_FOR_LEDGER" {
		t.Fatalf("allowlisted power status should create meter-state truth: %#v", row)
	}
}

func TestSemanticSignalSummaryRedactsUnsafeValue(t *testing.T) {
	signals := buildSemanticSignals(map[string]any{
		"alarm_type":   "AC_MAIN_FAIL",
		"alarm_status": "secret@example.com",
		"mainCause":    "must not be captured",
	})
	alarm := signals["alarm_type"].(map[string]any)
	if alarm["value"] != "AC_MAIN_FAIL" || alarm["value_ref"] == "" {
		t.Fatalf("safe alarm signal was not preserved: %#v", alarm)
	}
	unsafe := signals["alarm_status"].(map[string]any)
	if unsafe["value"] != "" || unsafe["redacted"] != true || unsafe["value_ref"] == "" {
		t.Fatalf("unsafe semantic signal was not redacted: %#v", unsafe)
	}
	if _, exists := signals["main_cause"]; exists {
		t.Fatalf("cause text must not enter semantic signals: %#v", signals)
	}
}

func TestInvalidExplicitEventStaysReviewOnly(t *testing.T) {
	eventType, source := normalizeTruthEventType(map[string]any{"event_type": "POWER_EVENT"})
	if eventType != "UNKNOWN" || source != "mapped_unknown" {
		t.Fatalf("invalid explicit event must remain review-only: %s %s", eventType, source)
	}
}

func TestStatusPayloadReturnsOnlySanitizedSemanticSignals(t *testing.T) {
	receivedAt := time.Date(2026, 7, 10, 3, 0, 0, 0, time.UTC)
	row := &storage.RequestStatus{
		RequestID:        "RAW-REQUEST-ID",
		ReceivedAt:       receivedAt,
		DetectedAt:       receivedAt,
		RequestJSON:      json.RawMessage(`{"semantic_capture_version":"v1","semantic_signals":{"alarm_type":{"present":true,"value":"AC_MAIN_FAIL","value_ref":"semantic_ref"}}}`),
		TruthEventType:   "OUTAGE",
		TruthValidation:  "READY_FOR_LEDGER",
		ProductionSend:   "blocked",
	}
	payload := statusPayload(row)
	signals := payload["semantic_signals"].(map[string]any)
	alarm := signals["alarm_type"].(map[string]any)
	if alarm["value"] != "AC_MAIN_FAIL" || alarm["value_ref"] != "semantic_ref" {
		t.Fatalf("operator payload lost sanitized semantic evidence: %#v", payload)
	}
	if payload["semantic_capture_version"] != "v1" {
		t.Fatalf("operator payload omitted semantic capture version: %#v", payload)
	}
	encoded, _ := json.Marshal(payload)
	if strings.Contains(string(encoded), "RAW-REQUEST-ID") {
		t.Fatalf("operator payload leaked raw request id: %s", encoded)
	}
}

func TestPostWithoutEventTypeStoresTruthObservationForReview(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-REVIEW-1","meter_no":"METER-1234","timestamp":"2026-06-19T17:04:00+07:00"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d: %s", res.Code, res.Body.String())
	}
	row := store.rows["AIS-REVIEW-1"]
	if row.TruthEventType != "UNKNOWN" || row.TruthValidation != "REVIEW_EVENT_TYPE" {
		t.Fatalf("unknown event type should be review-only: %#v", row)
	}
}

func TestPostRestoreBeforeOutageIsReviewOnly(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"request_id":"AIS-BAD-TRUTH-1","source_event_id":"SRC-BAD-TRUTH-1","event_type":"RESTORE","meter_no":"METER-1234","timestamp":"2026-06-19T17:04:00+07:00","outage_at":"2026-06-19T18:00:00+07:00","restore_at":"2026-06-19T17:30:00+07:00"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d: %s", res.Code, res.Body.String())
	}
	row := store.rows["AIS-BAD-TRUTH-1"]
	if row.TruthEventType != "RESTORE" || row.TruthValidation != "REVIEW_RESTORE_BEFORE_OUTAGE" {
		t.Fatalf("restore before outage should be review-only: %#v", row)
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

func TestMissingConfiguredAPIKeyFailsClosed(t *testing.T) {
	handler := NewServer(ServerConfig{}, newFakeStore())
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)
	if res.Code != http.StatusUnauthorized {
		t.Fatalf("missing server API key must fail closed, got %d", res.Code)
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
	requestRef, _ := payload["request_ref"].(string)
	if !strings.HasPrefix(requestRef, "request_") || payload["production_send"] != "blocked" || strings.Contains(res.Body.String(), "AIS-LOOKUP") {
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
	store.intervals = []storage.TruthInterval{
		{PairStatus: "OPEN", BridgeStatus: "METER_STATE_AWAITING_RESTORE"},
		{PairStatus: "REVIEW"},
		{PairStatus: "CLOSED", BridgeStatus: "METER_STATE_MODEL_READY", RestoreAt: ptrTime(time.Date(2026, 7, 7, 3, 30, 0, 0, time.UTC)), DurationMinutes: ptrFloat(30)},
	}
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
	if payload["outbox_dry_run_held"].(float64) != 1 || payload["dead_letters"].(float64) != 0 {
		t.Fatalf("outbox metrics missing: %#v", payload)
	}
	if payload["truth_quarantine_intervals"].(float64) != 2 || payload["truth_accuracy_eligible_intervals"].(float64) != 1 {
		t.Fatalf("truth interval quarantine metrics missing: %#v", payload)
	}
	if payload["truth_meter_state_open_intervals"].(float64) != 1 {
		t.Fatalf("meter-state open interval metric is missing: %#v", payload)
	}
	if payload["truth_strict_identity_intervals"].(float64) != 0 || payload["truth_meter_state_intervals"].(float64) != 1 || payload["model_ready_clean_truth_rows"].(float64) != 1 {
		t.Fatalf("meter-state metrics missing: %#v", payload)
	}
	if payload["model_truth_review_rows"].(float64) != 1 {
		t.Fatalf("review-only legacy request must remain visible in metrics: %#v", payload)
	}
	validationCounts := payload["truth_validation_counts"].(map[string]any)
	if validationCounts["REVIEW_EVENT_TYPE"].(float64) != 1 {
		t.Fatalf("metrics must expose only aggregate validation reasons: %#v", payload)
	}
	semanticCounts := payload["truth_event_semantic_counts"].(map[string]any)
	if semanticCounts["missing:UNKNOWN"].(float64) != 1 || payload["truth_stale_open_intervals"].(float64) != 0 {
		t.Fatalf("semantic metrics are incomplete: %#v", payload)
	}
	if strings.Contains(res.Body.String(), "AIS-METRICS") || strings.Contains(res.Body.String(), "REDACTED-METER-0000") {
		t.Fatalf("metrics leaked a request or meter identifier: %s", res.Body.String())
	}
	policy := payload["truth_interval_policy"].(map[string]any)
	if policy["ais_outbound_message"] != "hold_until_model_accuracy_gate_passes" {
		t.Fatalf("metrics must hold AIS outbound until model gate passes: %#v", policy)
	}
}

func TestTruthIntervalsEndpointIsAuthOnlyAndRedacted(t *testing.T) {
	store := newFakeStore()
	outageAt := time.Date(2026, 7, 7, 3, 0, 0, 0, time.UTC)
	store.intervals = []storage.TruthInterval{
		{
			IntervalID:      "ais-interval-1",
			Source:          "AIS",
			OutageRequestID: "AIS-OPEN-1",
			MeterHash:       "meterhash",
			MeterLast4:      "1234",
			SiteHash:        "sitehash",
			SiteLast4:       "T-99",
			OutageAt:        outageAt,
			PairStatus:      "OPEN",
			BridgeStatus:    "METER_STATE_AWAITING_RESTORE",
			EvidenceJSON:    json.RawMessage(`{"source":"go_postgres_truth_pairing","reason":"ready_outage_waiting_for_restore","outage_source_event_id":"SRC-SECRET-1","pair_key":"sitehash","production_send":"blocked"}`),
			ProductionSend:  "blocked",
			CreatedAt:       outageAt,
			UpdatedAt:       outageAt,
		},
	}
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)

	unauth := httptest.NewRequest(http.MethodGet, truthIntervalsPath, nil)
	unauthRes := httptest.NewRecorder()
	handler.ServeHTTP(unauthRes, unauth)
	if unauthRes.Code != http.StatusUnauthorized {
		t.Fatalf("expected auth on truth intervals, got %d", unauthRes.Code)
	}

	req := httptest.NewRequest(http.MethodGet, truthIntervalsPath+"?status=OPEN&limit=10", nil)
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)

	if res.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
	}
	body := res.Body.String()
	if strings.Contains(body, "SRC-SECRET-1") || strings.Contains(body, "pair_key") {
		t.Fatalf("truth interval endpoint leaked raw pairing evidence: %s", body)
	}
	payload := decodeBody(t, res)
	items := payload["items"].([]any)
	if items[0].(map[string]any)["bridge_status"] != "METER_STATE_AWAITING_RESTORE" {
		t.Fatalf("truth interval response omitted safe bridge status: %#v", payload)
	}
	if payload["production_send"] != "blocked" || payload["status_filter"] != "OPEN" {
		t.Fatalf("unsafe truth interval payload: %#v", payload)
	}
	if payload["count"].(float64) != 1 {
		t.Fatalf("expected one open interval, got %#v", payload)
	}
	item := items[0].(map[string]any)
	policy := item["review_policy"].(map[string]any)
	if policy["disposition"] != "quarantine_review_queue" {
		t.Fatalf("open interval must stay in quarantine review queue: %#v", policy)
	}
	if policy["model_accuracy_eligible"] != false || policy["production_readiness_evidence_eligible"] != false || policy["customer_send_eligible"] != false {
		t.Fatalf("open interval must be excluded from accuracy/readiness/send: %#v", policy)
	}
	if policy["ais_outbound_message"] != "hold_until_model_accuracy_gate_passes" {
		t.Fatalf("AIS outbound must stay held until model gate passes: %#v", policy)
	}
}

func TestProductionSendModeNeverEnablesRealSendWithoutGates(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{
		APIKey:             "pilot-key",
		ProductionSendMode: "auto_green_lane",
		CallbackTransport:  "real",
	}, store)
	body := `{"request_id":"AIS-GATE-BLOCK","meter_no":"REDACTED-METER-0000","timestamp":"2026-06-19T17:04:00+07:00"}`
	req := httptest.NewRequest(http.MethodPost, inboundPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()

	handler.ServeHTTP(res, req)

	if res.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d: %s", res.Code, res.Body.String())
	}
	row := store.rows["AIS-GATE-BLOCK"]
	if row.SendDecision != "blocked" || row.ProductionSend != "blocked" {
		t.Fatalf("unsafe send decision: %#v", row)
	}
	if row.CallbackOutboxStatus != "DRY_RUN_HELD" {
		t.Fatalf("expected dry-run outbox, got %#v", row)
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
	mu                  sync.Mutex
	rows                map[string]storage.RequestStatus
	intervals           []storage.TruthInterval
	callbackStatusCount map[string]int64
	inserted            int
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
func (f *fakeStore) ListTruthIntervals(ctx context.Context, status string, limit int) ([]storage.TruthInterval, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	status = strings.ToUpper(strings.TrimSpace(status))
	result := []storage.TruthInterval{}
	for _, interval := range f.intervals {
		if status != "" && status != "ALL" && interval.PairStatus != status {
			continue
		}
		result = append(result, interval)
		if len(result) >= limit {
			break
		}
	}
	return result, nil
}

func (f *fakeStore) InsertInbound(ctx context.Context, request storage.InboundRequest, truth storage.TruthObservation, callback storage.Callback, evidence storage.EvidenceTrace, etr storage.ETRCandidate, send storage.SendDecision, outbox storage.CallbackOutbox) (bool, error) {
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
		SendPolicyMode:     send.PolicyMode,
		SendEffectiveMode:  send.EffectiveMode,
		EligibilityStatus:  send.EligibilityStatus,
		SendDecision:       send.Decision,
		SendReason:         send.Reason,
		SendGateVersion:    send.GateVersion,
		CallbackOutboxStatus: outbox.Status,
		CallbackTransport: outbox.Transport,
		CallbackAttempts:  outbox.AttemptCount,
		TruthEventType:       truth.EventType,
		TruthEventTypeSource: truth.EventTypeSource,
		TruthValidation:      truth.ValidationStatus,
		TruthSourceEventRef:  truth.SourceEventHash,
		TruthSiteHash:        truth.SiteHash,
		TruthSiteLast4:       truth.SiteLast4,
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
	snapshot := &storage.MetricsSnapshot{
		CallbackCounts:           map[string]int64{},
		TruthValidationCounts:    map[string]int64{},
		TruthEventSemanticCounts: map[string]int64{},
	}
	for status, count := range f.callbackStatusCount {
		snapshot.CallbackCounts[status] = count
		if status == "SKIPPED_DUPLICATE" {
			snapshot.DuplicateCallbacks = count
		}
	}
	for _, row := range f.rows {
		snapshot.TotalRequests++
		if row.TruthValidation != "" && row.TruthValidation != "READY_FOR_LEDGER" {
			snapshot.ModelTruthReviewRows++
		}
		if row.LatestCallback != "" && snapshot.LatestReceivedAt == nil {
			receivedAt := row.ReceivedAt
			snapshot.LatestReceivedAt = &receivedAt
		}
		if row.ETRStatus == "NOT_READY_FOR_AUTO_SEND" {
			snapshot.NotReadyETR++
		}
		snapshot.PendingWorkerTraces++
		if row.CallbackOutboxStatus == "DRY_RUN_HELD" {
			snapshot.OutboxDryRunHeld++
		}
		if row.TruthEventType != "" {
			snapshot.TruthObservations++
		}
		if row.TruthValidation != "READY_FOR_LEDGER" {
			snapshot.TruthReviewNeeded++
		}
		if row.TruthValidation != "" {
			snapshot.TruthValidationCounts[row.TruthValidation]++
		}
		if row.TruthEventType == "OUTAGE" {
			snapshot.TruthOutageEvents++
		}
		if row.TruthEventType == "RESTORE" {
			snapshot.TruthRestoreEvents++
		}
		if row.TruthEventTypeSource != "" && row.TruthEventType != "" {
			snapshot.TruthEventSemanticCounts[row.TruthEventTypeSource+":"+row.TruthEventType]++
		}
	}
	for _, interval := range f.intervals {
		if interval.BridgeStatus == "STRICT_MODEL_READY" || interval.BridgeStatus == "STRICT_DURATION_REVIEW" {
			snapshot.TruthStrictIdentityIntervals++
		}
		if interval.BridgeStatus == "METER_STATE_MODEL_READY" || interval.BridgeStatus == "METER_STATE_DURATION_REVIEW" {
			snapshot.TruthMeterStateIntervals++
		}
		switch interval.PairStatus {
		case "OPEN":
			snapshot.TruthOpenIntervals++
			if interval.BridgeStatus == "METER_STATE_AWAITING_RESTORE" {
				snapshot.TruthMeterStateOpenIntervals++
			}
			snapshot.TruthQuarantineIntervals++
		case "REVIEW":
			snapshot.TruthReviewIntervals++
			snapshot.TruthQuarantineIntervals++
		case "CLOSED":
			snapshot.TruthClosedIntervals++
			if interval.BridgeStatus == "METER_STATE_MODEL_READY" && interval.RestoreAt != nil && interval.DurationMinutes != nil {
				snapshot.TruthAccuracyEligibleIntervals++
				snapshot.ModelReadyCleanTruthRows++
			} else {
				snapshot.TruthQuarantineIntervals++
			}
		}
	}
	return snapshot, nil
}

func ptrTime(value time.Time) *time.Time {
	return &value
}

func ptrFloat(value float64) *float64 {
	return &value
}
