package api

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPlaceResolveAPIRequiresAuthAndRejectsUnknownFields(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	body := `{"schema_version":"place-resolve.v1","query":"โรงพยาบาลบึงกาฬ"}`
	unauth := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, placeResolvePath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(unauth, req)
	if unauth.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", unauth.Code)
	}

	bad := httptest.NewRecorder()
	req = httptest.NewRequest(http.MethodPost, placeResolvePath, bytes.NewBufferString(`{"query":"โรงพยาบาลบึงกาฬ","unexpected":true}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	h.ServeHTTP(bad, req)
	if bad.Code != http.StatusBadRequest {
		t.Fatalf("expected strict JSON 400, got %d: %s", bad.Code, bad.Body.String())
	}
}

func TestPlaceResolveAPISinglePlaceDoesNotEchoRawQuery(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	rawQuery := "ไฟดับหน้าโรงพยาบาลบึงกาฬ"
	body := `{"schema_version":"place-resolve.v1","query":"` + rawQuery + `","limit":10}`
	req := httptest.NewRequest(http.MethodPost, placeResolvePath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
	}
	if strings.Contains(res.Body.String(), rawQuery) {
		t.Fatalf("raw query must not be echoed: %s", res.Body.String())
	}
	payload := decodeBody(t, res)
	if payload["schema_version"] != placeResolutionSchema || payload["gazetteer_version"] != "universal-place-gazetteer.v1" || payload["gazetteer_count"].(float64) != 104 {
		t.Fatalf("unexpected envelope: %#v", payload)
	}
	resolver := payload["resolver"].(map[string]any)
	if resolver["status"] != "MATCHED_SINGLE_PLACE" || resolver["outage_state"] != "UNDETERMINED" {
		t.Fatalf("unexpected resolver: %#v", resolver)
	}
}

func TestPlaceResolveAPIBrandOnlyAndGPSDisambiguation(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	call := func(body string) map[string]any {
		req := httptest.NewRequest(http.MethodPost, placeResolvePath, bytes.NewBufferString(body))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-API-Key", "pilot-key")
		res := httptest.NewRecorder()
		h.ServeHTTP(res, req)
		if res.Code != http.StatusOK {
			t.Fatalf("expected 200, got %d: %s", res.Code, res.Body.String())
		}
		return decodeBody(t, res)["resolver"].(map[string]any)
	}

	ambiguous := call(`{"query":"ไฟดับแถว 7-11"}`)
	if ambiguous["status"] != "AMBIGUOUS_PLACE" || ambiguous["match_count"].(float64) != 2 || ambiguous["location_used"] != false {
		t.Fatalf("brand only must remain ambiguous: %#v", ambiguous)
	}

	located := call(`{"query":"ไฟดับแถว 7-Eleven","location":{"lat":18.364986,"lon":103.6529,"accuracy_m":10,"source":"user_shared_location"}}`)
	if located["status"] != "MATCHED_SINGLE_PLACE_BY_LOCATION" || located["location_used"] != true {
		t.Fatalf("expected GPS branch disambiguation: %#v", located)
	}
	selected := located["selected_place"].(map[string]any)
	if selected["canonical_name"] != "เซเว่นอีเลฟเว่น" {
		t.Fatalf("unexpected selected branch: %#v", selected)
	}
}

func TestPlaceResolveAPIMultipleEvidenceNotCollapsedByGPS(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	body := `{"query":"โรงพยาบาลบึงกาฬ ใกล้ตลาดสดสุขาภิบาลบึงกาฬ","location":{"lat":18.3656,"lon":103.6532,"accuracy_m":10,"source":"user_shared_location"}}`
	req := httptest.NewRequest(http.MethodPost, placeResolvePath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusOK {
		t.Fatalf("expected 200: %d %s", res.Code, res.Body.String())
	}
	resolver := decodeBody(t, res)["resolver"].(map[string]any)
	if resolver["status"] != "MULTIPLE_PLACE_EVIDENCE" || resolver["location_used"] != false {
		t.Fatalf("independent evidence must remain multiple: %#v", resolver)
	}
}

func TestPlaceLookupAPIUsesStablePlaceID(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	resolveReq := httptest.NewRequest(http.MethodPost, placeResolvePath, bytes.NewBufferString(`{"query":"โรงพยาบาลบึงกาฬ"}`))
	resolveReq.Header.Set("Content-Type", "application/json")
	resolveReq.Header.Set("X-API-Key", "pilot-key")
	resolveRes := httptest.NewRecorder()
	h.ServeHTTP(resolveRes, resolveReq)
	payload := decodeBody(t, resolveRes)
	placeID := payload["resolver"].(map[string]any)["selected_place"].(map[string]any)["place_id"].(string)

	lookupReq := httptest.NewRequest(http.MethodGet, placePathPrefix+placeID, nil)
	lookupReq.Header.Set("X-API-Key", "pilot-key")
	lookupRes := httptest.NewRecorder()
	h.ServeHTTP(lookupRes, lookupReq)
	if lookupRes.Code != http.StatusOK {
		t.Fatalf("expected place lookup 200, got %d: %s", lookupRes.Code, lookupRes.Body.String())
	}
	lookup := decodeBody(t, lookupRes)
	if lookup["schema_version"] != placeAssetSchema || lookup["place"].(map[string]any)["place_id"] != placeID {
		t.Fatalf("bad place lookup: %#v", lookup)
	}

	missingReq := httptest.NewRequest(http.MethodGet, placePathPrefix+"plc_bk_0000000000000000", nil)
	missingReq.Header.Set("X-API-Key", "pilot-key")
	missingRes := httptest.NewRecorder()
	h.ServeHTTP(missingRes, missingReq)
	if missingRes.Code != http.StatusNotFound {
		t.Fatalf("expected missing place 404, got %d", missingRes.Code)
	}
}

func TestUnknownPlaceQueuesHashOnlyAndDiscoveryEndpointIsProtected(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	rawQuery := "ไฟดับแถวร้านลาบยายแดง"
	body := `{"schema_version":"place-resolve.v1","query":"` + rawQuery + `","location":{"lat":18.35512,"lon":103.65122,"accuracy_m":12,"source":"user_shared_location"}}`
	req := httptest.NewRequest(http.MethodPost, placeResolvePath, bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusOK { t.Fatalf("unknown place resolve expected 200: %d %s", res.Code, res.Body.String()) }
	payload := decodeBody(t, res)
	resolver := payload["resolver"].(map[string]any)
	if resolver["status"] != "NO_PLACE_MATCH" || resolver["discovery_status"] != "QUEUED_HASH_ONLY" { t.Fatalf("unexpected discovery result: %#v", resolver) }
	if strings.Contains(res.Body.String(), rawQuery) { t.Fatalf("raw query echoed in response: %s", res.Body.String()) }
	if len(store.unknownPlaces) != 1 { t.Fatalf("expected one hashed unknown observation, got %d", len(store.unknownPlaces)) }
	for _, row := range store.unknownPlaces {
		if row.QueryHash == "" || strings.Contains(row.QueryHash, "ยายแดง") { t.Fatalf("query must be hash only: %#v", row) }
		if row.LocationCell != "18.355,103.651" { t.Fatalf("expected coarse location cell, got %q", row.LocationCell) }
		if row.SourceChannel != "PLACE_API" { t.Fatalf("unexpected source channel: %#v", row) }
	}

	unauth := httptest.NewRecorder()
	h.ServeHTTP(unauth, httptest.NewRequest(http.MethodGet, placeDiscoveryQueuePath, nil))
	if unauth.Code != http.StatusUnauthorized { t.Fatalf("expected discovery queue 401, got %d", unauth.Code) }

	listReq := httptest.NewRequest(http.MethodGet, placeDiscoveryQueuePath+"?limit=10", nil)
	listReq.Header.Set("X-API-Key", "pilot-key")
	listRes := httptest.NewRecorder()
	h.ServeHTTP(listRes, listReq)
	if listRes.Code != http.StatusOK { t.Fatalf("queue list expected 200: %d %s", listRes.Code, listRes.Body.String()) }
	if strings.Contains(listRes.Body.String(), rawQuery) || strings.Contains(listRes.Body.String(), "ยายแดง") { t.Fatalf("discovery queue leaked raw query: %s", listRes.Body.String()) }
	listed := decodeBody(t, listRes)
	if listed["raw_query_persisted"] != false || listed["auto_add"] != false || listed["count"].(float64) != 1 { t.Fatalf("unsafe queue response: %#v", listed) }
}
