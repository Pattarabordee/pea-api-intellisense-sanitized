package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestBuengKanOutageResolvePersistsStructuredResultWithoutRawMessage(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key", OutageIntegrationAPIKey: "n8n-key"}, store)
	body := `{"schema_version":"outage-report.v1","source":{"channel":"LINE","event_id":"RAW-LINE-EVENT-SECRET-001","occurred_at":"2026-08-25T20:01:05+07:00","reporter_ref":"usr_a83f","conversation_ref":"conv_42ab"},"message":{"text":"บ้านดงหมากยางไฟดับ"},"location":{"lat":1.234567,"lon":2.345678,"accuracy_m":15,"source":"user_shared_location"}}`
	req := httptest.NewRequest(http.MethodPost, outageResolvePath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "n8n-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)

	if res.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	requestID := payload["request_id"].(string)
	if !strings.HasPrefix(requestID, "out_") || payload["mode"] != "shadow" || payload["production_send"] != "blocked" {
		t.Fatalf("unsafe response envelope: %#v", payload)
	}
	resolution := payload["resolution"].(map[string]any)
	if resolution["status"] != "VILLAGE_ONLY_SINGLE_FEEDER" || resolution["outage_state"] != "UNDETERMINED" {
		t.Fatalf("unexpected resolution: %#v", resolution)
	}
	inventory := resolution["service_inventory"].([]any)
	if len(inventory) != 1 {
		t.Fatalf("expected one service transformer, got %#v", inventory)
	}
	tx := inventory[0].(map[string]any)
	if tx["facility_id"] != "63-006344" || tx["asset_id_type"] != "PEA_GIS_FACILITYID" {
		t.Fatalf("bad transformer identity: %#v", tx)
	}
	location := tx["location"].(map[string]any)
	if location["lat"].(float64) == 0 || location["lon"].(float64) == 0 || location["crs"] != "EPSG:4326" {
		t.Fatalf("missing GIS coordinates: %#v", location)
	}
	row := store.outageResolutions[requestID]
	stored := string(row.ResultJSON)
	for _, secret := range []string{"RAW-LINE-EVENT-SECRET-001", "บ้านดงหมากยางไฟดับ", "1.234567", "2.345678", "usr_a83f", "conv_42ab"} {
		if strings.Contains(stored, secret) {
			t.Fatalf("persisted result leaked raw inbound value %q: %s", secret, stored)
		}
	}
	if row.SourceEventHash == "" || row.MessageHash == "" || row.ReporterRefHash == "" || row.ConversationRefHash == "" {
		t.Fatalf("expected hashed audit references: %#v", row)
	}

	get := httptest.NewRequest(http.MethodGet, outageResultPathPrefix+requestID, nil)
	get.Header.Set("Authorization", "Bearer n8n-key")
	getRes := httptest.NewRecorder()
	handler.ServeHTTP(getRes, get)
	if getRes.Code != http.StatusOK || !strings.Contains(getRes.Body.String(), "63-006344") {
		t.Fatalf("stored result lookup failed: %d %s", getRes.Code, getRes.Body.String())
	}
}

func TestBuengKanOutageResolveIsIdempotentByChannelAndEventID(t *testing.T) {
	store := newFakeStore()
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"schema_version":"outage-report.v1","source":{"channel":"FACEBOOK","event_id":"fb-event-1","occurred_at":"2026-08-25T20:01:05+07:00"},"message":{"text":"บ้านนาโนนไฟดับ"}}`
	var firstID string
	for i := 0; i < 2; i++ {
		req := httptest.NewRequest(http.MethodPost, outageResolvePath, bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-API-Key", "pilot-key")
		res := httptest.NewRecorder()
		handler.ServeHTTP(res, req)
		if i == 0 && res.Code != http.StatusCreated { t.Fatalf("first expected 201, got %d: %s", res.Code, res.Body.String()) }
		if i == 1 && res.Code != http.StatusOK { t.Fatalf("duplicate expected 200, got %d: %s", res.Code, res.Body.String()) }
		payload := decodeBody(t, res)
		id := payload["request_id"].(string)
		if firstID == "" { firstID = id } else if id != firstID { t.Fatalf("idempotency request id changed: %s vs %s", firstID, id) }
		if i == 1 && payload["duplicate"] != true { t.Fatalf("duplicate flag missing: %#v", payload) }
	}
	if len(store.outageResolutions) != 1 {
		t.Fatalf("expected one durable result, got %d", len(store.outageResolutions))
	}
}

func TestTransformerLookupReturnsCoordinatesAndNoPEANOField(t *testing.T) {
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	req := httptest.NewRequest(http.MethodGet, transformerPathPrefix+"63-006344", nil)
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)
	if res.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	asset := payload["asset"].(map[string]any)
	if asset["facility_id"] != "63-006344" || asset["asset_id_type"] != "PEA_GIS_FACILITYID" {
		t.Fatalf("unexpected asset: %#v", asset)
	}
	encoded, _ := json.Marshal(payload)
	if strings.Contains(strings.ToLower(string(encoded)), "peano") {
		t.Fatalf("asset API must not expose PEANO until explicitly approved: %s", encoded)
	}
	villages := payload["service_villages"].([]any)
	if len(villages) != 2 {
		t.Fatalf("expected two service villages: %#v", villages)
	}
}

func TestOutageResolveRejectsRawReporterIdentifierShape(t *testing.T) {
	handler := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	body := `{"schema_version":"outage-report.v1","source":{"channel":"LINE","event_id":"evt-1","occurred_at":"2026-08-25T20:01:05+07:00","reporter_ref":"John Doe"},"message":{"text":"บ้านนาโนนไฟดับ"}}`
	req := httptest.NewRequest(http.MethodPost, outageResolvePath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)
	if res.Code != http.StatusBadRequest {
		t.Fatalf("expected pseudonymous ref validation 400, got %d: %s", res.Code, res.Body.String())
	}
}
