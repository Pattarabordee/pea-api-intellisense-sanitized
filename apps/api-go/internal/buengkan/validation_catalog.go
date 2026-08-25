package buengkan

import (
	_ "embed"
	"encoding/json"
	"errors"
	"strings"
)

//go:embed data/validation_catalog_v1.json
var validationCatalogJSON []byte

type ValidationCatalogCandidate struct {
	FacilityID string `json:"facility_id"`
	FeederID string `json:"feeder_id"`
	Location TransformerLocation `json:"location"`
	ApproxDistanceM *float64 `json:"approx_source_to_lv_distance_m"`
}

type ValidationSourceLocation struct {
	Lat *float64 `json:"lat"`
	Lon *float64 `json:"lon"`
	CRS string `json:"crs"`
	Source string `json:"source"`
}

type ValidationPriorEvidence struct {
	Check string `json:"check"`
	Transformers []string `json:"transformers"`
	Rules []string `json:"rules"`
}

type ValidationCatalogItem struct {
	SourceType string `json:"source_type"`
	SourceRef string `json:"source_ref"`
	Label string `json:"label"`
	Category string `json:"category"`
	Priority string `json:"priority"`
	ValidationStatus string `json:"validation_status"`
	ResolverStatus string `json:"resolver_status"`
	KnownConflict bool `json:"known_conflict"`
	PriorEvidence ValidationPriorEvidence `json:"prior_evidence"`
	SourceLocation ValidationSourceLocation `json:"source_location"`
	Candidates []ValidationCatalogCandidate `json:"candidates"`
	CandidateCount int `json:"candidate_count"`
	Provenance string `json:"provenance"`
	CandidateScope string `json:"candidate_scope"`
	OutageState string `json:"outage_state"`
}

type validationCatalog struct {
	SchemaVersion string `json:"schema_version"`
	RegistryVersion int `json:"registry_version"`
	Scope string `json:"scope"`
	ItemCount int `json:"item_count"`
	SourceCounts map[string]int `json:"source_counts"`
	PriorityCounts map[string]int `json:"priority_counts"`
	PromotionPolicy string `json:"promotion_policy"`
	Items []ValidationCatalogItem `json:"items"`
	Guardrails map[string]any `json:"guardrails"`
}

var defaultValidationCatalog = mustLoadValidationCatalog()

func mustLoadValidationCatalog() validationCatalog {
	var c validationCatalog
	if err := json.Unmarshal(validationCatalogJSON, &c); err != nil { panic(err) }
	if c.SchemaVersion != "field-validation-catalog.v1" { panic("unexpected validation catalog version") }
	if c.RegistryVersion != RegistryVersion() { panic("validation catalog registry mismatch") }
	if mode, _ := c.Guardrails["mode"].(string); mode != Mode { panic("validation catalog mode mismatch") }
	if send, _ := c.Guardrails["production_send"].(string); send != ProductionSend { panic("validation catalog production_send mismatch") }
	return c
}

func ValidationCatalogPayload() any { return defaultValidationCatalog }

func ValidationCatalogItemByRef(sourceRef string) (ValidationCatalogItem, error) {
	ref := strings.TrimSpace(sourceRef)
	for _, item := range defaultValidationCatalog.Items {
		if item.SourceRef == ref { return item, nil }
	}
	return ValidationCatalogItem{}, errors.New("validation source not found")
}

func ValidationCatalogHasCandidate(item ValidationCatalogItem, facilityID string) bool {
	facilityID = strings.ToUpper(strings.TrimSpace(facilityID))
	if facilityID == "" { return false }
	for _, candidate := range item.Candidates {
		if strings.ToUpper(candidate.FacilityID) == facilityID { return true }
	}
	return false
}
