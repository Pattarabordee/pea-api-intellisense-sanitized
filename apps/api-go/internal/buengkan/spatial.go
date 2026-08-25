package buengkan

import (
	_ "embed"
	"encoding/json"
	"math"
	"sort"
)

//go:embed data/gps_lv_service_grid_v1.json
var gpsGridJSON []byte

type gpsGridTransformer struct {
	FacilityID  string   `json:"facility_id"`
	FeederID    string   `json:"feeder_id"`
	VillageKeys []string `json:"village_keys"`
}

type gpsGrid struct {
	SchemaVersion string                        `json:"schema_version"`
	RegistryVersion int                         `json:"registry_version"`
	CellSizeM     float64                       `json:"cell_size_m"`
	Transformers  map[string]gpsGridTransformer `json:"transformers"`
	Cells         map[string][]string           `json:"cells"`
	Guardrails    map[string]any                 `json:"guardrails"`
}

type LocationInput struct {
	Lat       float64
	Lon       float64
	AccuracyM *float64
	Source    string
}

type LocationCandidate struct {
	FacilityID          string  `json:"facility_id"`
	FeederID            string  `json:"feeder_id"`
	ApproxGridDistanceM float64 `json:"approx_grid_distance_m"`
}

type LocationEvidenceResult struct {
	Status           string              `json:"status"`
	UsedForTopology  bool                `json:"used_for_topology"`
	Source           string              `json:"source,omitempty"`
	AccuracyM        *float64            `json:"accuracy_m,omitempty"`
	SearchRadiusM    float64             `json:"search_radius_m,omitempty"`
	CandidateCount   int                 `json:"candidate_count"`
	Candidates       []LocationCandidate `json:"candidates"`
	EvidenceType     string              `json:"evidence_type"`
	OutageState      string              `json:"outage_state"`
}

var defaultGPSGrid = mustLoadGPSGrid()

func mustLoadGPSGrid() gpsGrid {
	var grid gpsGrid
	if err := json.Unmarshal(gpsGridJSON, &grid); err != nil {
		panic(err)
	}
	if grid.SchemaVersion != "gps-lv-service-grid.v1" || grid.RegistryVersion != RegistryVersion() {
		panic("Bueng Kan GPS grid version mismatch")
	}
	if grid.CellSizeM <= 0 || len(grid.Cells) == 0 || len(grid.Transformers) != 95 {
		panic("Bueng Kan GPS grid is incomplete")
	}
	if mode, _ := grid.Guardrails["mode"].(string); mode != Mode {
		panic("Bueng Kan GPS grid mode guardrail mismatch")
	}
	if send, _ := grid.Guardrails["production_send"].(string); send != ProductionSend {
		panic("Bueng Kan GPS grid production_send guardrail mismatch")
	}
	return grid
}

func webMercatorFromLonLat(lon, lat float64) (float64, float64) {
	if lat > 85.05112878 { lat = 85.05112878 }
	if lat < -85.05112878 { lat = -85.05112878 }
	x := 6378137.0 * lon * math.Pi / 180.0
	y := 6378137.0 * math.Log(math.Tan(math.Pi/4.0+(lat*math.Pi/180.0)/2.0))
	return x, y
}

func gpsCellKey(ix, iy int) string {
	return strconvInt(ix) + ":" + strconvInt(iy)
}

func strconvInt(value int) string {
	if value == 0 { return "0" }
	negative := value < 0
	if negative { value = -value }
	const digits = "0123456789"
	buf := make([]byte, 0, 16)
	for value > 0 {
		buf = append(buf, digits[value%10])
		value /= 10
	}
	if negative { buf = append(buf, '-') }
	for i, j := 0, len(buf)-1; i < j; i, j = i+1, j-1 { buf[i], buf[j] = buf[j], buf[i] }
	return string(buf)
}

func locationSearchRadius(accuracy *float64) float64 {
	if accuracy == nil { return 75.0 }
	radius := *accuracy + 25.0
	if radius < 35.0 { radius = 35.0 }
	if radius > 150.0 { radius = 150.0 }
	return radius
}

func locationConfidence(accuracy *float64, candidateCount int) string {
	if candidateCount != 1 { return "MEDIUM" }
	if accuracy == nil { return "MEDIUM" }
	if *accuracy <= 30 { return "HIGH" }
	if *accuracy <= 75 { return "MEDIUM" }
	return "LOW"
}

func MatchLocation(input LocationInput) LocationEvidenceResult {
	evidence := LocationEvidenceResult{
		Status:          "NO_LV_SERVICE_CELL_WITHIN_RADIUS",
		UsedForTopology: false,
		Source:          input.Source,
		AccuracyM:       input.AccuracyM,
		Candidates:      []LocationCandidate{},
		EvidenceType:    "GPS_TO_TRACE_CONFIRMED_LV_SERVICE_GRID",
		OutageState:     OutageState,
	}
	if input.AccuracyM != nil && *input.AccuracyM > 150 {
		evidence.Status = "LOCATION_ACCURACY_TOO_LOW"
		return evidence
	}
	x, y := webMercatorFromLonLat(input.Lon, input.Lat)
	cellSize := defaultGPSGrid.CellSizeM
	radius := locationSearchRadius(input.AccuracyM)
	evidence.SearchRadiusM = radius
	cx := int(math.Floor(x / cellSize))
	cy := int(math.Floor(y / cellSize))
	ring := int(math.Ceil(radius/cellSize)) + 1
	diagonal := cellSize * math.Sqrt2
	minDistance := map[string]float64{}
	for ix := cx - ring; ix <= cx + ring; ix++ {
		for iy := cy - ring; iy <= cy + ring; iy++ {
			centerX := (float64(ix) + 0.5) * cellSize
			centerY := (float64(iy) + 0.5) * cellSize
			distance := math.Hypot(x-centerX, y-centerY)
			if distance > radius+diagonal { continue }
			for _, tx := range defaultGPSGrid.Cells[gpsCellKey(ix, iy)] {
				prior, ok := minDistance[tx]
				if !ok || distance < prior { minDistance[tx] = distance }
			}
		}
	}
	if len(minDistance) == 0 { return evidence }
	type ranked struct { tx string; distance float64 }
	rankedRows := make([]ranked, 0, len(minDistance))
	for tx, distance := range minDistance { rankedRows = append(rankedRows, ranked{tx, distance}) }
	sort.Slice(rankedRows, func(i, j int) bool {
		if rankedRows[i].distance == rankedRows[j].distance { return rankedRows[i].tx < rankedRows[j].tx }
		return rankedRows[i].distance < rankedRows[j].distance
	})
	margin := 30.0
	if input.AccuracyM != nil {
		margin = *input.AccuracyM
		if margin < 20 { margin = 20 }
		if margin > 60 { margin = 60 }
	}
	best := rankedRows[0].distance
	for _, row := range rankedRows {
		if row.distance > best+margin { break }
		meta, ok := defaultGPSGrid.Transformers[row.tx]
		if !ok { continue }
		evidence.Candidates = append(evidence.Candidates, LocationCandidate{
			FacilityID: row.tx,
			FeederID: meta.FeederID,
			ApproxGridDistanceM: math.Round(row.distance*10) / 10,
		})
	}
	evidence.CandidateCount = len(evidence.Candidates)
	if evidence.CandidateCount == 1 {
		evidence.Status = "GPS_SINGLE_TX_CANDIDATE"
	} else if evidence.CandidateCount > 1 {
		evidence.Status = "GPS_AMBIGUOUS_MULTI_TX"
	}
	return evidence
}

func ResolveWithLocation(text string, location *LocationInput) ResolveResult {
	result := Resolve(text)
	if location == nil { return result }
	evidence := MatchLocation(*location)
	result.LocationEvidence = &evidence
	if result.Status == "UNSUPPORTED_VILLAGE" {
		return result
	}
	if evidence.Status == "LOCATION_ACCURACY_TOO_LOW" || len(evidence.Candidates) == 0 {
		return result
	}

	candidateIDs := make([]string, 0, len(evidence.Candidates))
	for _, candidate := range evidence.Candidates { candidateIDs = append(candidateIDs, candidate.FacilityID) }

	// If text already narrowed the footprint, GPS must agree with it.
	if len(result.SelectedTransformers) > 0 {
		selectedSet := transformerIDSet(result.SelectedTransformers)
		candidateIDs = intersectIDs(candidateIDs, selectedSet)
		if len(candidateIDs) == 0 {
			return markLocationConflict(result, evidence, "GPS ขัดกับจุดสังเกต/Topology ที่ข้อความระบุ")
		}
	} else if result.VillageKey != "" && len(result.ServiceInventory) > 0 {
		// A GPS candidate outside the matched village service inventory is a conflict, not an override.
		serviceSet := transformerIDSet(result.ServiceInventory)
		candidateIDs = intersectIDs(candidateIDs, serviceSet)
		if len(candidateIDs) == 0 {
			return markLocationConflict(result, evidence, "GPS ไม่ทับกับ LV service inventory ของหมู่บ้านที่ระบุ")
		}
	}

	selected := transformerResults(candidateIDs, "GPS_LV_SERVICE_CELL")
	if len(selected) == 0 { return result }
	evidence.UsedForTopology = true
	result.LocationEvidence = &evidence
	result.Supported = true
	result.SelectedTransformers = selected
	result.CandidateScope = "GPS_LV_SERVICE_CELL"
	result.MatchedClues = appendUnique(result.MatchedClues, "gps_lv_service_grid_v1")
	result.TopologyConfidence = locationConfidence(location.AccuracyM, len(selected))
	result.NeedsMoreInformation = []string{"operational_outage_confirmation"}
	if len(selected) == 1 {
		result.Status = "RESOLVED_GPS_FOOTPRINT"
		result.SelectedFeeder = selected[0].FeederID
		result.Message = "พิกัดที่ผู้ใช้แชร์ตรงกับ LV service grid ของหม้อแปลงที่ผ่าน TraceDown QA; ยังไม่ใช่การยืนยันว่าไฟดับจริง"
		return result
	}
	result.Status = "AMBIGUOUS_GPS_FOOTPRINT"
	result.SelectedFeeder = commonFeeder(selected)
	result.Message = "พิกัดช่วย narrow LV footprint ได้ แต่ยังมีมากกว่าหนึ่งหม้อแปลงในช่วงความคลาดเคลื่อนของตำแหน่ง"
	result.NeedsMoreInformation = []string{"more_precise_location_or_landmark", "operational_outage_confirmation"}
	return result
}

func markLocationConflict(result ResolveResult, evidence LocationEvidenceResult, message string) ResolveResult {
	evidence.UsedForTopology = false
	result.LocationEvidence = &evidence
	result.Status = "EVIDENCE_CONFLICT"
	result.SelectedTransformers = []TransformerResult{}
	result.SelectedFeeder = ""
	result.TopologyConfidence = "LOW"
	result.Message = message + "; ระบบ fail closed และไม่เลือก TX"
	result.NeedsMoreInformation = []string{"verify_location_and_place_name", "operational_outage_confirmation"}
	return result
}

func transformerIDSet(items []TransformerResult) map[string]bool {
	out := map[string]bool{}
	for _, item := range items { if item.FacilityID != "" { out[item.FacilityID] = true } }
	return out
}

func intersectIDs(ids []string, allowed map[string]bool) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, id := range ids {
		if allowed[id] && !seen[id] { seen[id] = true; out = append(out, id) }
	}
	sort.Strings(out)
	return out
}

func appendUnique(items []string, value string) []string {
	for _, item := range items { if item == value { return items } }
	return append(items, value)
}

func commonFeeder(items []TransformerResult) string {
	if len(items) == 0 { return "" }
	feeder := items[0].FeederID
	for _, item := range items[1:] { if item.FeederID != feeder { return "" } }
	return feeder
}
