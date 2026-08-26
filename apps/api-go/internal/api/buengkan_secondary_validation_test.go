package api

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestSecondaryValidationCatalogIsProtectedAndSanitized(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	unauth := httptest.NewRecorder()
	h.ServeHTTP(unauth, httptest.NewRequest(http.MethodGet, buengKanSecondaryValidationCatalogPath, nil))
	if unauth.Code != http.StatusUnauthorized { t.Fatalf("expected 401, got %d", unauth.Code) }

	req := httptest.NewRequest(http.MethodGet, buengKanSecondaryValidationCatalogPath, nil)
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusOK { t.Fatalf("catalog expected 200, got %d: %s", res.Code, res.Body.String()) }
	body := res.Body.String()
	upper := strings.ToUpper(body)
	for _, forbidden := range []string{`"PEANO":`, `"ACCOUNTNUMBER":`, `"CUSTOMERNAME":`, `"INSTALLATIONID":`} {
		if strings.Contains(upper, forbidden) { t.Fatalf("catalog leaked forbidden field %s", forbidden) }
	}
	payload := decodeBody(t, res)
	catalog := payload["catalog"].(map[string]any)
	if int(catalog["item_count"].(float64)) != 93 { t.Fatalf("expected 93 catalog items: %#v", catalog["item_count"]) }
	semantic := catalog["semantic_counts"].(map[string]any)
	if semantic["RESIDENTIAL_COMPLEX"].(float64) != 2 || semantic["COMMERCIAL_RETAIL"].(float64) != 4 { t.Fatalf("unexpected semantic counts: %#v", semantic) }
	if payload["mode"] != "shadow" || payload["production_send"] != "blocked" { t.Fatalf("unsafe envelope: %#v", payload) }
}

func TestSecondaryValidationSingleCandidatePersistsCatalogTruth(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"receipt_id":"BKV-UNIT-001","source_type":"POI","source_ref":"poi:34499","validator_ref":"validator_unit_1","verdict":"CORRECT","selected_transformer":"","correction_transformer":"","correction_feeder":""}`
	req := httptest.NewRequest(http.MethodPost, buengKanSecondaryValidationPath, bytes.NewBufferString(body))
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusCreated { t.Fatalf("expected 201, got %d: %s", res.Code, res.Body.String()) }
	payload := decodeBody(t, res)
	if payload["selected_transformer"] != "65-006228" || payload["validation_scope"] != "POI_POINT_FIELD_VALIDATION_ONLY" || payload["auto_promoted"] != false { t.Fatalf("unexpected response: %#v", payload) }
	if len(store.secondaryValidation) != 1 { t.Fatalf("expected one stored validation") }
	row := store.secondaryValidation[0]
	if row.SourceLabel != "โรงพยาบาลบึงกาฬ" || row.ValidationScope != "POI_POINT_FIELD_VALIDATION_ONLY" || row.Priority != "P1_HIGH_VALUE_SINGLE" || row.SelectedTransformer != "65-006228" {
		t.Fatalf("must persist trusted catalog fields: %#v", row)
	}
}

func TestSecondaryValidationRoadScopeIsRepresentativePointOnly(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	body := `{"receipt_id":"BKV-ROAD-001","source_type":"ROAD_SOI","source_ref":"road:098a8fe5679b12d9","validator_ref":"validator_unit_1","verdict":"CORRECT"}`
	req := httptest.NewRequest(http.MethodPost, buengKanSecondaryValidationPath, bytes.NewBufferString(body))
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusCreated { t.Fatalf("road validation expected 201: %d %s", res.Code, res.Body.String()) }
	payload := decodeBody(t, res)
	if payload["validation_scope"] != "ROAD_REPRESENTATIVE_POINT_FIELD_VALIDATION_ONLY" || payload["auto_promoted"] != false {
		t.Fatalf("road validation scope must remain representative-point only: %#v", payload)
	}
	if len(store.secondaryValidation) != 1 || store.secondaryValidation[0].ValidationScope != "ROAD_REPRESENTATIVE_POINT_FIELD_VALIDATION_ONLY" {
		t.Fatalf("road ledger scope mismatch: %#v", store.secondaryValidation)
	}
}

func TestSecondaryValidationAmbiguousRequiresCatalogCandidate(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	missing := `{"receipt_id":"BKV-UNIT-002","source_type":"POI","source_ref":"poi:33566","validator_ref":"validator_unit_1","verdict":"CORRECT","selected_transformer":""}`
	req := httptest.NewRequest(http.MethodPost, buengKanSecondaryValidationPath, bytes.NewBufferString(missing))
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusBadRequest || !strings.Contains(res.Body.String(), "SELECTED_TRANSFORMER_REQUIRED") { t.Fatalf("expected selected candidate gate: %d %s", res.Code, res.Body.String()) }

	tampered := `{"receipt_id":"BKV-UNIT-003","source_type":"POI","source_ref":"poi:33566","validator_ref":"validator_unit_1","verdict":"CORRECT","selected_transformer":"00-000000"}`
	req = httptest.NewRequest(http.MethodPost, buengKanSecondaryValidationPath, bytes.NewBufferString(tampered))
	req.Header.Set("X-API-Key", "pilot-key")
	res = httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusBadRequest || !strings.Contains(res.Body.String(), "INVALID_SELECTED_TRANSFORMER") { t.Fatalf("expected catalog candidate gate: %d %s", res.Code, res.Body.String()) }

	valid := `{"receipt_id":"BKV-UNIT-004","source_type":"POI","source_ref":"poi:33566","validator_ref":"validator_unit_1","verdict":"CORRECT","selected_transformer":"43-113173"}`
	req = httptest.NewRequest(http.MethodPost, buengKanSecondaryValidationPath, bytes.NewBufferString(valid))
	req.Header.Set("X-API-Key", "pilot-key")
	res = httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusCreated { t.Fatalf("valid ambiguous candidate expected 201: %d %s", res.Code, res.Body.String()) }
}

func TestSecondaryValidationNoCoverageCannotBeConfirmedCorrect(t *testing.T) {
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, newFakeStore())
	body := `{"receipt_id":"BKV-UNIT-005","source_type":"POI","source_ref":"poi:24761","validator_ref":"validator_unit_1","verdict":"CORRECT"}`
	req := httptest.NewRequest(http.MethodPost, buengKanSecondaryValidationPath, bytes.NewBufferString(body))
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusBadRequest || !strings.Contains(res.Body.String(), "NO_CANDIDATE_TO_CONFIRM") { t.Fatalf("expected no-candidate gate: %d %s", res.Code, res.Body.String()) }
}

func TestSecondaryValidationListCounts(t *testing.T) {
	store := newFakeStore()
	h := NewServer(ServerConfig{APIKey: "pilot-key"}, store)
	for i, verdict := range []string{"CORRECT", "INCORRECT", "UNSURE"} {
		body := `{"receipt_id":"BKV-LIST-00` + string(rune('1'+i)) + `","source_type":"POI","source_ref":"poi:34499","validator_ref":"validator_unit_1","verdict":"` + verdict + `"}`
		req := httptest.NewRequest(http.MethodPost, buengKanSecondaryValidationPath, bytes.NewBufferString(body))
		req.Header.Set("X-API-Key", "pilot-key")
		res := httptest.NewRecorder()
		h.ServeHTTP(res, req)
		if res.Code != http.StatusCreated { t.Fatalf("insert %s failed: %d %s", verdict, res.Code, res.Body.String()) }
	}
	req := httptest.NewRequest(http.MethodGet, buengKanSecondaryValidationPath+"?limit=10", nil)
	req.Header.Set("X-API-Key", "pilot-key")
	res := httptest.NewRecorder()
	h.ServeHTTP(res, req)
	if res.Code != http.StatusOK { t.Fatalf("list expected 200: %d %s", res.Code, res.Body.String()) }
	payload := decodeBody(t, res)
	summary := payload["summary"].(map[string]any)
	if summary["total"].(float64) != 3 || summary["correct"].(float64) != 1 || summary["incorrect"].(float64) != 1 || summary["unsure"].(float64) != 1 { t.Fatalf("bad summary: %#v", summary) }
	if payload["auto_promotion"] != false { t.Fatalf("validation must not auto-promote") }
}
