package buengkan

import (
	_ "embed"
	"encoding/json"
	"errors"
	"regexp"
	"sort"
	"strings"
)

//go:embed data/registry_v5.json
var registryJSON []byte

const (
	Mode           = "shadow"
	ProductionSend = "blocked"
	OutageState    = "UNDETERMINED"
)

type TopologyPrior struct {
	Feeder         string  `json:"feeder"`
	CoreMeterCount int     `json:"core_meter_count"`
	TopologyShare  float64 `json:"topology_share"`
}

type LandmarkRule struct {
	ID               string   `json:"id"`
	Phrases          []string `json:"phrases"`
	Feeder           string   `json:"feeder"`
	Transformers     []string `json:"transformers"`
	Strength         float64  `json:"strength"`
	GenericAmbiguous bool     `json:"generic_ambiguous"`
}

type ProtectionZone struct {
	Gate                  string    `json:"gate"`
	Devices               []string  `json:"devices"`
	Coverage              *float64  `json:"coverage"`
	DownstreamMeterCount  *int      `json:"downstream_meter_count"`
	TargetTransformers    []string  `json:"target_transformers"`
}

type Village struct {
	VillageKey                    string                         `json:"village_key"`
	VillageName                   string                         `json:"village_name"`
	Aliases                       []string                       `json:"aliases"`
	TopologyPrior                 []TopologyPrior                `json:"topology_prior"`
	VillageTransformers           []string                       `json:"village_transformers"`
	VillageTransformersByFeeder   map[string][]string            `json:"village_transformers_by_feeder"`
	LandmarkRules                 []LandmarkRule                 `json:"landmark_rules"`
	ProtectionZones               map[string]ProtectionZone      `json:"protection_zones"`
	QAGate                        string                         `json:"qa_gate"`
	CoreCoverage                  float64                        `json:"core_coverage"`
}

type ExcludedVillage struct {
	VillageKey   string  `json:"village_key"`
	VillageName  string  `json:"village_name"`
	Gate         string  `json:"gate"`
	Reason       string  `json:"reason"`
	CoreCoverage float64 `json:"core_coverage"`
}

type Transformer struct {
	FacilityID string  `json:"facility_id"`
	FeederID   string  `json:"feeder_id"`
	Lat        float64 `json:"lat"`
	Lon        float64 `json:"lon"`
	CRS        string  `json:"crs"`
	Source     string  `json:"source"`
}

type registry struct {
	SchemaVersion      int                    `json:"schema_version"`
	Scope              string                 `json:"scope"`
	Villages           []Village              `json:"villages"`
	ExcludedVillages   []ExcludedVillage      `json:"excluded_villages"`
	Guardrails         map[string]any         `json:"guardrails"`
	TransformerCatalog map[string]Transformer `json:"transformer_catalog"`
}

type ProtectionZoneResult struct {
	Gate                 string   `json:"gate,omitempty"`
	Devices              []string `json:"devices"`
	Coverage             *float64 `json:"coverage,omitempty"`
	DownstreamMeterCount *int     `json:"downstream_meter_count,omitempty"`
}

type TransformerResult struct {
	FacilityID     string             `json:"facility_id"`
	AssetIDType    string             `json:"asset_id_type"`
	FeederID       string             `json:"feeder_id"`
	Location       TransformerLocation `json:"location"`
	EvidenceType   string             `json:"evidence_type"`
	CandidateScope string             `json:"candidate_scope"`
	OutageState    string             `json:"outage_state"`
}

type TransformerLocation struct {
	Lat    float64 `json:"lat"`
	Lon    float64 `json:"lon"`
	CRS    string  `json:"crs"`
	Source string  `json:"source"`
}

type ResolveResult struct {
	RegistryVersion          int                    `json:"registry_version"`
	Status                   string                 `json:"status"`
	Supported                bool                   `json:"supported"`
	VillageKey               string                 `json:"village_key,omitempty"`
	VillageName              string                 `json:"village_name,omitempty"`
	Message                  string                 `json:"message"`
	SelectedFeeder           string                 `json:"selected_feeder,omitempty"`
	CandidateScope           string                 `json:"candidate_scope"`
	TopologyConfidence       string                 `json:"topology_confidence,omitempty"`
	TopologyPrior            []TopologyPrior        `json:"topology_prior"`
	ProtectionZone           *ProtectionZoneResult  `json:"protection_zone,omitempty"`
	MatchedClues             []string               `json:"matched_clues"`
	ServiceInventory         []TransformerResult    `json:"service_inventory"`
	SelectedTransformers     []TransformerResult    `json:"selected_transformers"`
	ExcludedReason           string                 `json:"excluded_reason,omitempty"`
	CoreCoverage             *float64               `json:"core_coverage,omitempty"`
	OutageState              string                 `json:"outage_state"`
	NeedsMoreInformation     []string               `json:"needs_more_information"`
	RequiredConfirmation     []string               `json:"required_confirmation"`
	LocationEvidence         *LocationEvidenceResult `json:"location_evidence,omitempty"`
}

type ServiceVillage struct {
	VillageKey  string `json:"village_key"`
	VillageName string `json:"village_name"`
}

type AssetLookup struct {
	RegistryVersion int              `json:"registry_version"`
	Transformer     TransformerResult `json:"transformer"`
	ServiceVillages []ServiceVillage `json:"service_villages"`
	Mode            string           `json:"mode"`
	ProductionSend  string           `json:"production_send"`
}

type matchedClue struct {
	RuleID       string
	Feeder       string
	Transformers []string
	Strength     float64
}

var (
	defaultRegistry = mustLoadRegistry()
	mooDotPattern   = regexp.MustCompile(`ม\.\s*(\d{1,2})`)
	mooPattern      = regexp.MustCompile(`หมู่\s*(\d{1,2})`)
	threeRPattern   = regexp.MustCompile(`3r\s*[- ]?\s*01`)
)

var strongZoneGates = map[string]bool{
	"STRONG_LOCAL_ZONE_CANDIDATE":   true,
	"STRONG_PAIR_ZONE_CANDIDATE":    true,
	"STRONG_BOUNDED_ZONE_CANDIDATE": true,
}

func mustLoadRegistry() registry {
	var r registry
	if err := json.Unmarshal(registryJSON, &r); err != nil {
		panic(err)
	}
	if r.SchemaVersion != 5 {
		panic("unexpected Bueng Kan registry version")
	}
	if mode, _ := r.Guardrails["mode"].(string); mode != Mode {
		panic("Bueng Kan registry mode guardrail mismatch")
	}
	if send, _ := r.Guardrails["production_send"].(string); send != ProductionSend {
		panic("Bueng Kan registry production_send guardrail mismatch")
	}
	return r
}

func RegistryVersion() int { return defaultRegistry.SchemaVersion }

func NormalizeText(input string) string {
	value := strings.ToLower(strings.TrimSpace(input))
	value = strings.NewReplacer(
		"\u200b", "", "\u200c", "", "\u200d", "", "\ufeff", "",
		"เเสน", "แสน", "บิ้ก", "บิ๊ก", "หมู่บ้าน", "บ้าน",
	).Replace(value)
	value = mooDotPattern.ReplaceAllString(value, "ม.$1")
	value = mooPattern.ReplaceAllString(value, "หมู่$1")
	value = threeRPattern.ReplaceAllString(value, "3r-01")
	value = strings.NewReplacer("\n", " ", "\r", " ", "\t", " ", ",", " ", ";", " ", ":", " ", "(", " ", ")", " ", "[", " ", "]", " ", "{", " ", "}", " ").Replace(value)
	return strings.Join(strings.Fields(value), " ")
}

func contains(normalizedText, phrase string) bool {
	p := NormalizeText(phrase)
	return p != "" && strings.Contains(normalizedText, p)
}

func Resolve(text string) ResolveResult {
	normalized := NormalizeText(text)
	if normalized == "" {
		return baseResult("OUTSIDE_PILOT_SCOPE", false, nil, "กรุณาระบุชื่อหมู่บ้านหรือจุดสังเกตในพื้นที่ทดสอบ")
	}
	villages := candidateVillages(normalized)
	if len(villages) == 0 {
		if excluded := findExcluded(normalized); excluded != nil {
			coverage := excluded.CoreCoverage
			result := baseResult("UNSUPPORTED_VILLAGE", false, nil, "หมู่บ้านนี้ยังไม่ผ่าน GIS topology gate จึงไม่คาดเดาหม้อแปลง")
			result.VillageKey = excluded.VillageKey
			result.VillageName = excluded.VillageName
			result.ExcludedReason = excluded.Reason
			result.CoreCoverage = &coverage
			return result
		}
		return baseResult("OUTSIDE_PILOT_SCOPE", false, nil, "ยังไม่พบหมู่บ้านนี้ในชุดทดสอบบึงกาฬ")
	}
	if len(villages) > 1 {
		return baseResult("AMBIGUOUS_VILLAGE", false, nil, "ข้อความตรงกับมากกว่าหนึ่งหมู่บ้าน กรุณาระบุชื่อหมู่บ้านให้ชัดเจน")
	}
	village := villages[0]
	result := baseResult("", true, village, "")
	clues := append(matchedLandmarks(normalized, village), matchedZoneDevices(normalized, village)...)
	if len(clues) == 0 {
		feeders := uniqueVillageFeeders(village)
		if len(feeders) == 1 {
			result.Status = "VILLAGE_ONLY_SINGLE_FEEDER"
			result.Message = "ระบุ feeder ได้จาก LV service topology ของหมู่บ้าน แต่ยังไม่ใช่หลักฐานว่าอุปกรณ์กำลังดับจริง"
			result.SelectedFeeder = feeders[0]
			result.TopologyConfidence = "HIGH"
			result.ProtectionZone = zoneResult(village, feeders[0])
			result.NeedsMoreInformation = []string{"operational_outage_confirmation"}
			return result
		}
		result.Status = "VILLAGE_ONLY_MULTI_FEEDER"
		result.Message = "หมู่บ้านนี้รับบริการจากหลาย feeder/TX; แสดง service inventory ทั้งหมดและรอซอย จุดสังเกต หรือพิกัดเพื่อ narrow footprint"
		result.TopologyConfidence = "LOW"
		result.NeedsMoreInformation = []string{"landmark_or_soi", "shared_location"}
		return result
	}

	scores := map[string]float64{}
	transformers := map[string]map[string]bool{}
	for _, clue := range clues {
		scores[clue.Feeder] += clue.Strength
		if transformers[clue.Feeder] == nil {
			transformers[clue.Feeder] = map[string]bool{}
		}
		for _, tx := range clue.Transformers {
			transformers[clue.Feeder][tx] = true
		}
	}
	type rankedFeeder struct{ feeder string; score float64 }
	ranked := make([]rankedFeeder, 0, len(scores))
	for feeder, score := range scores { ranked = append(ranked, rankedFeeder{feeder, score}) }
	sort.Slice(ranked, func(i, j int) bool {
		if ranked[i].score == ranked[j].score { return ranked[i].feeder < ranked[j].feeder }
		return ranked[i].score > ranked[j].score
	})
	best := ranked[0]
	secondScore := 0.0
	if len(ranked) > 1 { secondScore = ranked[1].score }
	if len(ranked) > 1 && (best.score == secondScore || best.score-secondScore < 25) {
		result.Status = "AMBIGUOUS_FOOTPRINT"
		result.Message = "จุดสังเกตยังชี้ได้มากกว่าหนึ่ง feeder กรุณาระบุรายละเอียดเพิ่ม"
		result.TopologyConfidence = "LOW"
		result.MatchedClues = clueIDs(clues)
		result.NeedsMoreInformation = []string{"more_specific_landmark", "shared_location"}
		return result
	}
	selectedIDs := sortedKeys(transformers[best.feeder])
	result.Status = "RESOLVED_FOOTPRINT"
	result.Message = "พบ GIS topology candidate จากข้อมูลหมู่บ้านและจุดสังเกตในข้อความ"
	result.SelectedFeeder = best.feeder
	result.CandidateScope = "NARROWED_FOOTPRINT"
	result.SelectedTransformers = transformerResults(selectedIDs, "NARROWED_FOOTPRINT")
	result.ProtectionZone = zoneResult(village, best.feeder)
	result.MatchedClues = clueIDs(clues)
	result.NeedsMoreInformation = []string{"operational_outage_confirmation"}
	gate := ""
	if zone, ok := village.ProtectionZones[best.feeder]; ok { gate = zone.Gate }
	if best.score >= 100 && strongZoneGates[gate] { result.TopologyConfidence = "HIGH" } else { result.TopologyConfidence = "MEDIUM" }
	return result
}

func baseResult(status string, supported bool, village *Village, message string) ResolveResult {
	result := ResolveResult{
		RegistryVersion:      defaultRegistry.SchemaVersion,
		Status:               status,
		Supported:            supported,
		Message:              message,
		CandidateScope:       "VILLAGE_SERVICE_INVENTORY",
		MatchedClues:         []string{},
		ServiceInventory:     []TransformerResult{},
		SelectedTransformers: []TransformerResult{},
		TopologyPrior:        []TopologyPrior{},
		OutageState:          OutageState,
		NeedsMoreInformation: []string{},
		RequiredConfirmation: []string{"ReportPO/ETR/OMS", "SCADA/สถานะอุปกรณ์", "การยืนยันจากหน้างาน"},
	}
	if village != nil {
		result.VillageKey = village.VillageKey
		result.VillageName = village.VillageName
		result.TopologyPrior = append([]TopologyPrior{}, village.TopologyPrior...)
		result.ServiceInventory = transformerResults(village.VillageTransformers, "VILLAGE_SERVICE_INVENTORY")
	}
	return result
}

func candidateVillages(text string) []*Village {
	result := []*Village{}
	for i := range defaultRegistry.Villages {
		v := &defaultRegistry.Villages[i]
		for _, alias := range v.Aliases {
			if contains(text, alias) { result = append(result, v); break }
		}
	}
	return result
}

func findExcluded(text string) *ExcludedVillage {
	for i := range defaultRegistry.ExcludedVillages {
		v := &defaultRegistry.ExcludedVillages[i]
		aliases := []string{v.VillageName, "บ้าน" + v.VillageName, "บ." + v.VillageName}
		for _, alias := range aliases { if contains(text, alias) { return v } }
	}
	return nil
}

func matchedLandmarks(text string, village *Village) []matchedClue {
	specificBigSuea := strings.Contains(text, "หน้าบิ๊กเสือ") || strings.Contains(text, "ตรงข้ามบิ๊กเสือ")
	result := []matchedClue{}
	for _, rule := range village.LandmarkRules {
		if rule.GenericAmbiguous && specificBigSuea { continue }
		matched := false
		for _, phrase := range rule.Phrases { if contains(text, phrase) { matched = true; break } }
		if !matched || rule.Feeder == "" { continue }
		result = append(result, matchedClue{RuleID: rule.ID, Feeder: rule.Feeder, Transformers: append([]string{}, rule.Transformers...), Strength: rule.Strength})
	}
	return result
}

func matchedZoneDevices(text string, village *Village) []matchedClue {
	result := []matchedClue{}
	feeders := make([]string, 0, len(village.ProtectionZones))
	for feeder := range village.ProtectionZones { feeders = append(feeders, feeder) }
	sort.Strings(feeders)
	for _, feeder := range feeders {
		zone := village.ProtectionZones[feeder]
		strength := 80.0
		if strongZoneGates[zone.Gate] { strength = 105 } else if zone.Gate == "BROAD_UPSTREAM_ZONE_CANDIDATE" { strength = 85 }
		for _, device := range zone.Devices {
			if contains(text, device) {
				result = append(result, matchedClue{RuleID: "registry_device:" + device, Feeder: feeder, Transformers: append([]string{}, zone.TargetTransformers...), Strength: strength})
			}
		}
	}
	return result
}

func uniqueVillageFeeders(village *Village) []string {
	seen := map[string]bool{}
	for _, item := range village.TopologyPrior { if item.Feeder != "" { seen[item.Feeder] = true } }
	return sortedKeys(seen)
}

func zoneResult(village *Village, feeder string) *ProtectionZoneResult {
	zone, ok := village.ProtectionZones[feeder]
	if !ok { return nil }
	return &ProtectionZoneResult{Gate: zone.Gate, Devices: append([]string{}, zone.Devices...), Coverage: zone.Coverage, DownstreamMeterCount: zone.DownstreamMeterCount}
}

func transformerResults(ids []string, scope string) []TransformerResult {
	seen := map[string]bool{}
	result := []TransformerResult{}
	for _, id := range ids {
		if seen[id] { continue }
		seen[id] = true
		tx, ok := defaultRegistry.TransformerCatalog[id]
		if !ok { continue }
		result = append(result, TransformerResult{
			FacilityID: tx.FacilityID,
			AssetIDType: "PEA_GIS_FACILITYID",
			FeederID: tx.FeederID,
			Location: TransformerLocation{Lat: tx.Lat, Lon: tx.Lon, CRS: tx.CRS, Source: tx.Source},
			EvidenceType: "LV_SERVICE_TRACE_CONFIRMED",
			CandidateScope: scope,
			OutageState: OutageState,
		})
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].FeederID == result[j].FeederID { return result[i].FacilityID < result[j].FacilityID }
		return result[i].FeederID < result[j].FeederID
	})
	return result
}

func LookupTransformer(facilityID string) (AssetLookup, error) {
	id := strings.ToUpper(strings.TrimSpace(facilityID))
	tx, ok := defaultRegistry.TransformerCatalog[id]
	if !ok { return AssetLookup{}, errors.New("transformer not found") }
	villages := []ServiceVillage{}
	for _, v := range defaultRegistry.Villages {
		for _, candidate := range v.VillageTransformers {
			if candidate == id {
				villages = append(villages, ServiceVillage{VillageKey: v.VillageKey, VillageName: v.VillageName})
				break
			}
		}
	}
	sort.Slice(villages, func(i, j int) bool { return villages[i].VillageKey < villages[j].VillageKey })
	result := transformerResults([]string{tx.FacilityID}, "ASSET_LOOKUP")
	return AssetLookup{RegistryVersion: defaultRegistry.SchemaVersion, Transformer: result[0], ServiceVillages: villages, Mode: Mode, ProductionSend: ProductionSend}, nil
}

func clueIDs(clues []matchedClue) []string {
	seen := map[string]bool{}
	for _, clue := range clues { if clue.RuleID != "" { seen[clue.RuleID] = true } }
	return sortedKeys(seen)
}

func sortedKeys[T any](m map[string]T) []string {
	keys := make([]string, 0, len(m))
	for key := range m { keys = append(keys, key) }
	sort.Strings(keys)
	return keys
}
