package api

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

const chatbotTestSessionRef = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

func chatbotTestBody(ticketID, houseOrVillage, subdistrict, district, province, serviceType string) string {
	return `{
  "schema_version":"pea-chatbot-report.v1",
  "source":{
    "system":"n8n-pea-buengkan",
    "channel":"chat",
    "event_id":"` + ticketID + `",
    "session_ref":"` + chatbotTestSessionRef + `",
    "occurred_at":"2026-08-26T13:32:02+07:00"
  },
  "report":{
    "ticket_id":"` + ticketID + `",
    "service_type":"` + serviceType + `",
    "incident_detail":"ไฟดับ",
    "location":{
      "house_or_village":"` + houseOrVillage + `",
      "subdistrict":"` + subdistrict + `",
      "district":"` + district + `",
      "province":"` + province + `"
    },
    "customer":{
      "name":"ผู้ใช้ทดสอบ",
      "phone":"0000000000"
    },
    "confirmed":true,
    "completed_at":"2026-08-26T06:32:02.508Z"
  }
}`
}

func callChatbotReport(t *testing.T, h http.Handler, body string, key string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, chatbotReportsPath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json; charset=utf-8")
	if key != "" {
		req.Header.Set("X-API-Key", key)
	}
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	return res
}

func TestChatbotCompatibilityAcceptsPowerOutageWithoutInventingETA(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key", OutageIntegrationAPIKey: "n8n-key"}, store)
	body := chatbotTestBody("PEA-20260826-771DC7", "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "เมืองบึงกาฬ", "บึงกาฬ", "power_outage")
	res := callChatbotReport(t, h, body, "n8n-key")
	if res.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["schema_version"] != chatbotAckSchema || payload["ticket_id"] != "PEA-20260826-771DC7" {
		t.Fatalf("unexpected compatibility envelope: %#v", payload)
	}
	if payload["accept_status"] != "ACCEPTED" || payload["bot_action"] != "SHOW_ACK" {
		t.Fatalf("unsafe chatbot action: %#v", payload)
	}
	message := payload["customer_message"].(map[string]any)
	if message["template_key"] != "ACK" {
		t.Fatalf("must use ACK while outage is unconfirmed: %#v", message)
	}
	context := payload["context"].(map[string]any)
	if context["feeder_id"] != "BUA03" || context["outage_state"] != "UNDETERMINED" {
		t.Fatalf("unexpected safe context: %#v", context)
	}
	encoded := res.Body.String()
	for _, forbidden := range []string{"eta_restore", "work_order_id", "cause", "SHOW_ACK_WITH_ETA", "SHOW_EXISTING_OUTAGE"} {
		if strings.Contains(encoded, forbidden) {
			t.Fatalf("response invented operational state %q: %s", forbidden, encoded)
		}
	}
	requestID := payload["request_id"].(string)
	stored := string(store.outageResolutions[requestID].ResultJSON)
	for _, pii := range []string{"ผู้ใช้ทดสอบ", "0000000000"} {
		if strings.Contains(stored, pii) {
			t.Fatalf("customer PII must not be persisted by compatibility adapter: %q in %s", pii, stored)
		}
	}
}

func TestChatbotCompatibilityIsIdempotentByTicketID(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key", OutageIntegrationAPIKey: "n8n-key"}, store)
	body := chatbotTestBody("PEA-20260826-A1B2C3", "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "power_outage")
	first := callChatbotReport(t, h, body, "n8n-key")
	second := callChatbotReport(t, h, body, "n8n-key")
	if first.Code != http.StatusCreated || second.Code != http.StatusOK {
		t.Fatalf("expected 201 then 200, got %d and %d", first.Code, second.Code)
	}
	firstPayload := decodeBody(t, first)
	secondPayload := decodeBody(t, second)
	if firstPayload["request_id"] != secondPayload["request_id"] || secondPayload["duplicate"] != true {
		t.Fatalf("idempotency contract failed: first=%#v second=%#v", firstPayload, secondPayload)
	}
	if len(store.outageResolutions) != 1 {
		t.Fatalf("expected one durable outage resolution, got %d", len(store.outageResolutions))
	}
}

func TestChatbotCompatibilityFailsClosedOnProvinceConflictWithoutPersisting(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key", OutageIntegrationAPIKey: "n8n-key"}, store)
	body := chatbotTestBody("PEA-20260826-B1C2D3", "บ้านนาโนน หมู่ 4", "บึงกาฬ", "บึงกาฬ", "นครพนม", "power_outage")
	res := callChatbotReport(t, h, body, "n8n-key")
	if res.Code != http.StatusOK {
		t.Fatalf("expected safe 200 needs-more-info response, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["accept_status"] != "NEEDS_MORE_INFO" || payload["bot_action"] != "ASK_MORE_LOCATION" {
		t.Fatalf("province conflict must fail closed: %#v", payload)
	}
	params := payload["customer_message"].(map[string]any)["params"].(map[string]any)
	if params["missing_field"] != "province" {
		t.Fatalf("expected province correction request: %#v", params)
	}
	if len(store.outageResolutions) != 0 {
		t.Fatalf("needs-more-info preflight must not freeze an incomplete ticket in idempotent storage")
	}
}

func TestChatbotCompatibilityDetectsVillageMooConflict(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key", OutageIntegrationAPIKey: "n8n-key"}, store)
	body := chatbotTestBody("PEA-20260826-C1D2E3", "บ้านนาโนน หมู่ 3", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "power_outage")
	res := callChatbotReport(t, h, body, "n8n-key")
	if res.Code != http.StatusOK {
		t.Fatalf("expected safe 200 needs-more-info response, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	params := payload["customer_message"].(map[string]any)["params"].(map[string]any)
	if payload["accept_status"] != "NEEDS_MORE_INFO" || params["missing_field"] != "house_or_village" {
		t.Fatalf("Moo conflict must ask for corrected village information: %#v", payload)
	}
	if len(store.outageResolutions) != 0 {
		t.Fatalf("Moo conflict must not persist an outage resolution")
	}
}

func TestChatbotCompatibilityRejectsUnsupportedServiceType(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key", OutageIntegrationAPIKey: "n8n-key"}, newFakeStore())
	body := chatbotTestBody("PEA-20260826-D1E2F3", "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "meter_reconnection")
	res := callChatbotReport(t, h, body, "n8n-key")
	if res.Code != http.StatusBadRequest || !strings.Contains(res.Body.String(), "power_outage") {
		t.Fatalf("meter_reconnection must remain explicitly unsupported in adapter v1: %d %s", res.Code, res.Body.String())
	}
}

func TestChatbotCompatibilityStatusReturnsReceivedOnly(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key", OutageIntegrationAPIKey: "n8n-key"}, store)
	ticketID := "PEA-20260826-E1F2A3"
	body := chatbotTestBody(ticketID, "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "power_outage")
	post := callChatbotReport(t, h, body, "n8n-key")
	if post.Code != http.StatusCreated {
		t.Fatalf("setup failed: %d %s", post.Code, post.Body.String())
	}

	req := httptest.NewRequest(http.MethodGet, chatbotReportsPath+"/"+ticketID+"/status", nil)
	req.Header.Set("X-API-Key", "n8n-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["found"] != true || payload["bot_action"] != "SHOW_STATUS" {
		t.Fatalf("unexpected status envelope: %#v", payload)
	}
	message := payload["customer_message"].(map[string]any)
	if message["template_key"] != "STATUS_RECEIVED" {
		t.Fatalf("shadow adapter must not claim assigned/in-progress/restored: %#v", message)
	}
	for _, forbidden := range []string{"STATUS_ASSIGNED", "STATUS_IN_PROGRESS", "STATUS_RESTORED", "eta_restore"} {
		if strings.Contains(res.Body.String(), forbidden) {
			t.Fatalf("status endpoint invented operational state %q: %s", forbidden, res.Body.String())
		}
	}
}

func TestChatbotCompatibilityStatusNotFoundUses200Contract(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key", OutageIntegrationAPIKey: "n8n-key"}, newFakeStore())
	req := httptest.NewRequest(http.MethodGet, chatbotReportsPath+"/PEA-20260826-FFFFFF/status", nil)
	req.Header.Set("X-API-Key", "n8n-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusOK {
		t.Fatalf("expected 200 not-found contract, got %d: %s", res.Code, res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["found"] != false || payload["bot_action"] != "STATUS_NOT_FOUND" {
		t.Fatalf("unexpected not-found response: %#v", payload)
	}
}

func TestChatbotCompatibilityRequiresDedicatedOrPilotCredential(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key", OutageIntegrationAPIKey: "n8n-key"}, newFakeStore())
	body := chatbotTestBody("PEA-20260826-F1A2B3", "บ้านดงหมากยาง หมู่ 7", "บึงกาฬ", "บึงกาฬ", "บึงกาฬ", "power_outage")
	res := callChatbotReport(t, h, body, "wrong-key")
	if res.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d: %s", res.Code, res.Body.String())
	}
}
