package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

func aspNetDate(t time.Time) string {
	return fmt.Sprintf("/Date(%d)/", t.UnixMilli())
}

func plannedSourceRecord(id, province, area, detail string, start, end time.Time) plannedOutageSourceRecord {
	return plannedOutageSourceRecord{
		Region:     1,
		Area:       area,
		ProvinceID: 77,
		Province:   province,
		OfficeID:   "BKL",
		PEAOffice:  "กฟส.บึงกาฬ",
		Detail:     detail,
		StartDate:  aspNetDate(start),
		EndDate:    aspNetDate(end),
		OutageID:   id,
	}
}

func plannedSnapshot(records ...plannedOutageSourceRecord) plannedOutageSnapshot {
	raw, _ := json.Marshal(records)
	return plannedOutageSnapshot{
		Records:    records,
		FetchedAt:  time.Date(2026, 8, 26, 6, 0, 0, 0, time.UTC),
		SourceHash: hashRaw(raw),
		SourceMode: plannedOutageSourcePrimary,
	}
}

func TestPlannedOutageDeterministicActiveMatch(t *testing.T) {
	occurred := time.Date(2026, 8, 26, 6, 32, 2, 0, time.UTC)
	record := plannedSourceRecord(
		"notice-1", "บึงกาฬ", "บ้านดงหมากยาง หมู่ 7", "ปรับปรุงระบบจำหน่ายและเปลี่ยนอุปกรณ์",
		occurred.Add(-time.Hour), occurred.Add(2*time.Hour),
	)
	result := evaluatePlannedOutageSnapshot(
		plannedSnapshot(record),
		chatbotLocationInput{HouseOrVillage: "บ้านดงหมากยาง หมู่ 7", Province: "บึงกาฬ"},
		occurred,
		false,
	)
	if result.Decision != "MATCHED" || result.NoticeID != "notice-1" {
		t.Fatalf("expected deterministic MATCHED, got %#v", result)
	}
	matched := result.Evidence["matched_notice"].(plannedOutageNotice)
	if matched.ReasonCode != "MAINTENANCE" {
		t.Fatalf("expected MAINTENANCE reason code, got %#v", matched)
	}
	if result.Evidence["planned_end_is_restoration_eta"] != false {
		t.Fatalf("planned_end must never be presented as restoration ETA: %#v", result.Evidence)
	}
	if result.Evidence["ai_decision_allowed"] != false {
		t.Fatalf("AI must not be allowed to promote a match: %#v", result.Evidence)
	}
}

func TestPlannedOutagePartialAreaIsAmbiguous(t *testing.T) {
	occurred := time.Date(2026, 8, 26, 6, 32, 2, 0, time.UTC)
	record := plannedSourceRecord(
		"notice-partial", "บึงกาฬ", "บ้านดงหมากยางบางส่วน ตั้งแต่หน้าโรงเรียนถึงวัด", "ตัดต้นไม้ใกล้แนวสายไฟ",
		occurred.Add(-time.Hour), occurred.Add(time.Hour),
	)
	result := evaluatePlannedOutageSnapshot(
		plannedSnapshot(record),
		chatbotLocationInput{HouseOrVillage: "บ้านดงหมากยาง หมู่ 7", Province: "บึงกาฬ"},
		occurred,
		false,
	)
	if result.Decision != "AMBIGUOUS" {
		t.Fatalf("partial-area notice must fail closed as AMBIGUOUS, got %#v", result)
	}
	if result.NoticeID != "" {
		t.Fatalf("ambiguous result must not select a notice: %#v", result)
	}
}

func TestPlannedOutageUpcomingNoticeDoesNotExplainCurrentOutage(t *testing.T) {
	occurred := time.Date(2026, 8, 26, 6, 32, 2, 0, time.UTC)
	record := plannedSourceRecord(
		"notice-future", "บึงกาฬ", "บ้านดงหมากยาง หมู่ 7", "ปรับปรุงระบบจำหน่าย",
		occurred.Add(30*time.Minute), occurred.Add(3*time.Hour),
	)
	result := evaluatePlannedOutageSnapshot(
		plannedSnapshot(record),
		chatbotLocationInput{HouseOrVillage: "บ้านดงหมากยาง หมู่ 7", Province: "บึงกาฬ"},
		occurred,
		false,
	)
	if result.Decision != "NO_MATCH" {
		t.Fatalf("future plan must not explain current outage, got %#v", result)
	}
	upcoming := result.Evidence["upcoming_candidate_ids"].([]string)
	if len(upcoming) != 1 || upcoming[0] != "notice-future" {
		t.Fatalf("future plan should remain context only: %#v", result.Evidence)
	}
}

func TestPlannedOutageUnavailableDoesNotUseStaleCacheAsNoMatch(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "unavailable", http.StatusServiceUnavailable)
	}))
	defer server.Close()

	stale := plannedSnapshot(plannedSourceRecord(
		"stale-notice", "บึงกาฬ", "บ้านดงหมากยาง หมู่ 7", "ปรับปรุงระบบจำหน่าย",
		time.Now().Add(-time.Hour), time.Now().Add(time.Hour),
	))
	stale.FetchedAt = time.Now().Add(-time.Hour)
	gate := &plannedOutageGate{
		mode:       plannedOutageModeShadow,
		baseURL:    server.URL,
		normalTTL:  15 * time.Minute,
		hotTTL:     5 * time.Minute,
		httpClient: &http.Client{Timeout: 500 * time.Millisecond},
		cache:      plannedOutageCache{snapshot: stale},
	}
	result := gate.check(t.Context(), chatbotLocationInput{HouseOrVillage: "บ้านดงหมากยาง หมู่ 7", Province: "บึงกาฬ"}, time.Now())
	if result.Decision != "UNAVAILABLE" || !result.SourceStale {
		t.Fatalf("stale source after refresh failure must be UNAVAILABLE, got %#v", result)
	}
	if result.Evidence["stale_cache_used_for_match"] != false {
		t.Fatalf("stale cache must never be used to declare MATCH/NO_MATCH: %#v", result.Evidence)
	}
}

func TestPlannedOutageShadowPersistsDecisionWithoutChangingChatbotAckOrPII(t *testing.T) {
	occurred := time.Date(2026, 8, 26, 6, 32, 2, 0, time.UTC)
	record := plannedSourceRecord(
		"notice-shadow", "บึงกาฬ", "บ้านดงหมากยาง หมู่ 7", "ปรับปรุงระบบจำหน่าย",
		occurred.Add(-time.Hour), occurred.Add(2*time.Hour),
	)
	server := plannedOutageTestServer(t, []plannedOutageSourceRecord{record})
	defer server.Close()

	store := newFakeStore()
	h := NewServer(ServerConfig{
		APIKey:                  "pilot-key",
		OutageIntegrationAPIKey: "n8n-key",
		PlannedOutageMode:       "shadow",
		PlannedOutageBaseURL:    server.URL,
		PlannedOutageTimeoutMS:  500,
	}, store)
	body := chatbotTestBody("PEA-20260826-123ABC", "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "power_outage")
	res := callChatbotReport(t, h, body, "n8n-key")
	if res.Code != http.StatusCreated {
		t.Fatalf("shadow gate must preserve existing chatbot response, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["bot_action"] != "SHOW_ACK" || payload["accept_status"] != "ACCEPTED" {
		t.Fatalf("shadow mode must not enforce planned outage yet: %#v", payload)
	}
	rows := store.plannedDecisions["PEA-20260826-123ABC"]
	if len(rows) != 1 || rows[0].Decision != "MATCHED" || rows[0].Mode != "shadow" {
		t.Fatalf("expected one shadow planned-outage audit row: %#v", rows)
	}
	if len(store.outageResolutions) != 1 {
		t.Fatalf("shadow mode must still run PEA Intellisense Core, got %d core rows", len(store.outageResolutions))
	}
	stored := string(rows[0].EvidenceJSON) + string(rows[0].RawSnapshotJSON)
	for _, forbidden := range []string{"ผู้ใช้ทดสอบ", "0000000000"} {
		if strings.Contains(stored, forbidden) {
			t.Fatalf("planned outage audit must not persist customer PII %q: %s", forbidden, stored)
		}
	}
}

func TestPlannedOutageSourceChangeCreatesRevision(t *testing.T) {
	occurred := time.Date(2026, 8, 26, 6, 32, 2, 0, time.UTC)
	var mu sync.Mutex
	records := []plannedOutageSourceRecord{plannedSourceRecord(
		"notice-revision", "บึงกาฬ", "บ้านดงหมากยาง หมู่ 7", "ปรับปรุงระบบจำหน่าย",
		occurred.Add(-time.Hour), occurred.Add(2*time.Hour),
	)}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/Home/GetOutages" {
			http.NotFound(w, r)
			return
		}
		mu.Lock()
		copyRecords := append([]plannedOutageSourceRecord{}, records...)
		mu.Unlock()
		_ = json.NewEncoder(w).Encode(plannedOutageListResponse{Draw: "1", RecordsFiltered: len(copyRecords), RecordsTotal: len(copyRecords), Data: copyRecords})
	}))
	defer server.Close()

	store := newFakeStore()
	gate := newPlannedOutageGate(ServerConfig{PlannedOutageMode: "shadow", PlannedOutageBaseURL: server.URL, PlannedOutageTimeoutMS: 500}, store)
	input := plannedOutageTestInput("PEA-20260826-456DEF")
	first := gate.checkAndPersist(t.Context(), input)
	if first.Decision != "MATCHED" {
		t.Fatalf("setup match failed: %#v", first)
	}
	mu.Lock()
	records[0].Detail = "ตัดต้นไม้ใกล้แนวสายไฟ"
	mu.Unlock()
	gate.mu.Lock()
	gate.cache.snapshot.FetchedAt = time.Now().Add(-time.Hour)
	gate.mu.Unlock()
	second := gate.checkAndPersist(t.Context(), input)
	if second.Decision != "MATCHED" {
		t.Fatalf("revised source should remain matched: %#v", second)
	}
	rows := store.plannedDecisions[input.Report.TicketID]
	if len(rows) != 2 || rows[1].Revision != 2 || !rows[1].SourceChanged {
		t.Fatalf("source change must create a revision-aware audit row: %#v", rows)
	}
}

func plannedOutageTestInput(ticketID string) chatbotReportRequest {
	return chatbotReportRequest{
		SchemaVersion: chatbotRequestSchema,
		Source: chatbotSourceInput{
			System:     "n8n-pea-buengkan",
			Channel:    "chat",
			EventID:    ticketID,
			SessionRef: chatbotTestSessionRef,
			OccurredAt: "2026-08-26T13:32:02+07:00",
		},
		Report: chatbotReportInput{
			TicketID:       ticketID,
			ServiceType:    "power_outage",
			IncidentDetail: "ไฟดับ",
			Location: chatbotLocationInput{
				HouseOrVillage: "บ้านดงหมากยาง หมู่ 7",
				Subdistrict:    "บึงกาฬ",
				District:       "บึงกาฬ",
				Province:       "บึงกาฬ",
			},
			Customer:    chatbotCustomerInput{Name: "ผู้ใช้ทดสอบ", Phone: "0000000000"},
			Confirmed:   true,
			CompletedAt: "2026-08-26T06:32:02.508Z",
		},
	}
}

func plannedOutageTestServer(t *testing.T, records []plannedOutageSourceRecord) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/Home/GetOutages" || r.Method != http.MethodPost {
			http.NotFound(w, r)
			return
		}
		_ = json.NewEncoder(w).Encode(plannedOutageListResponse{
			Draw:            "1",
			RecordsFiltered: len(records),
			RecordsTotal:    len(records),
			Data:            records,
		})
	}))
}
