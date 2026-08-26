package buengkan

import (
	_ "embed"
	"encoding/json"
	"errors"
	"math"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

//go:embed data/place_gazetteer_v1.json
var placeGazetteerJSON []byte

const PlaceGazetteerVersion = "universal-place-gazetteer.v1"

type PlaceLocation struct {
	Lat    float64 `json:"lat"`
	Lon    float64 `json:"lon"`
	CRS    string  `json:"crs"`
	Source string  `json:"source"`
}

type PlaceSource struct {
	SourceRef    string `json:"source_ref"`
	SourceSystem string `json:"source_system"`
	Role         string `json:"role"`
}

type PlaceTransformerCandidate struct {
	FacilityID                    string               `json:"facility_id"`
	FeederID                      string               `json:"feeder_id"`
	Location                      *TransformerLocation `json:"location"`
	ApproxSourceToLVDistanceM     *float64             `json:"approx_source_to_lv_distance_m"`
	DownstreamMeterCount          *int                 `json:"downstream_meter_count,omitempty"`
	PotentialImpactSemantics      string               `json:"potential_impact_semantics,omitempty"`
	RouteFromPEABuengKan          *TransformerRoute    `json:"route_from_pea_buengkan,omitempty"`
	EvidenceType                  string               `json:"evidence_type"`
}

type PlaceTopology struct {
	Status                string                      `json:"status"`
	CandidateScope        string                      `json:"candidate_scope"`
	TransformerCandidates []PlaceTransformerCandidate `json:"transformer_candidates"`
	CandidateCount        int                         `json:"candidate_count"`
	OutageState           string                      `json:"outage_state"`
}

type PlaceValidation struct {
	Status        string `json:"status"`
	Priority      string `json:"priority"`
	KnownConflict bool   `json:"known_conflict"`
	AutoPromotion bool   `json:"auto_promotion"`
}

type Place struct {
	PlaceID           string          `json:"place_id"`
	CanonicalName     string          `json:"canonical_name"`
	Aliases           []string        `json:"aliases"`
	NormalizedAliases []string        `json:"normalized_aliases"`
	PlaceType         string          `json:"place_type"`
	PlaceKind         string          `json:"place_kind"`
	Scope             string          `json:"scope"`
	Location          *PlaceLocation  `json:"location"`
	Sources           []PlaceSource   `json:"sources"`
	Topology          PlaceTopology   `json:"topology"`
	Validation        PlaceValidation `json:"validation"`
}

type placeGazetteer struct {
	SchemaVersion       string         `json:"schema_version"`
	Scope               string         `json:"scope"`
	RegistryVersion     int            `json:"registry_version"`
	PlaceCount          int            `json:"place_count"`
	KindCounts          map[string]int `json:"kind_counts"`
	TypeCounts          map[string]int `json:"type_counts"`
	SourceCounts        map[string]int `json:"source_counts"`
	AmbiguousAliasCount int            `json:"ambiguous_alias_count"`
	Places              []Place        `json:"places"`
	Guardrails          map[string]any `json:"guardrails"`
}

type PlaceResolveLocationInput struct {
	Lat       float64
	Lon       float64
	AccuracyM *float64
	Source    string
}

type PlaceMatch struct {
	PlaceID           string          `json:"place_id"`
	CanonicalName     string          `json:"canonical_name"`
	Aliases           []string        `json:"aliases"`
	PlaceType         string          `json:"place_type"`
	PlaceKind         string          `json:"place_kind"`
	Scope             string          `json:"scope"`
	Location          *PlaceLocation  `json:"location,omitempty"`
	Sources           []PlaceSource   `json:"sources"`
	Topology          PlaceTopology   `json:"topology"`
	Validation        PlaceValidation `json:"validation"`
	MatchedAliases    []string        `json:"matched_aliases"`
	ApproxDistanceM   *float64        `json:"approx_distance_m,omitempty"`
}

type PlaceResolveResult struct {
	GazetteerVersion     string       `json:"gazetteer_version"`
	Status               string       `json:"status"`
	Matches              []PlaceMatch `json:"matches"`
	SelectedPlace        *PlaceMatch  `json:"selected_place,omitempty"`
	MatchCount           int          `json:"match_count"`
	LocationReceived     bool         `json:"location_received"`
	LocationUsed         bool         `json:"location_used"`
	CommonMatchedAliases []string     `json:"common_matched_aliases"`
	NeedsMoreInformation []string     `json:"needs_more_information"`
	DiscoveryStatus      string       `json:"discovery_status"`
	OutageState          string       `json:"outage_state"`
}

var defaultPlaceGazetteer = mustLoadPlaceGazetteer()

func mustLoadPlaceGazetteer() placeGazetteer {
	var g placeGazetteer
	if err := json.Unmarshal(placeGazetteerJSON, &g); err != nil {
		panic(err)
	}
	if g.SchemaVersion != PlaceGazetteerVersion {
		panic("unexpected place gazetteer version")
	}
	if g.RegistryVersion != RegistryVersion() {
		panic("place gazetteer registry mismatch")
	}
	if mode, _ := g.Guardrails["mode"].(string); mode != Mode {
		panic("place gazetteer mode mismatch")
	}
	if send, _ := g.Guardrails["production_send"].(string); send != ProductionSend {
		panic("place gazetteer production_send mismatch")
	}
	return g
}

func PlaceGazetteerCount() int { return defaultPlaceGazetteer.PlaceCount }

func PlaceGazetteerGuardrails() map[string]any {
	return defaultPlaceGazetteer.Guardrails
}

func LookupPlace(placeID string) (PlaceMatch, error) {
	id := strings.TrimSpace(placeID)
	for _, place := range defaultPlaceGazetteer.Places {
		if place.PlaceID == id {
			m := publicPlaceMatch(place, nil)
			return m, nil
		}
	}
	return PlaceMatch{}, errors.New("place not found")
}

func ResolvePlace(query string, location *PlaceResolveLocationInput, limit int) PlaceResolveResult {
	if limit <= 0 || limit > 25 {
		limit = 10
	}
	q := normalizePlaceSearch(query)
	result := PlaceResolveResult{
		GazetteerVersion:     PlaceGazetteerVersion,
		Status:               "NO_PLACE_MATCH",
		Matches:              []PlaceMatch{},
		MatchCount:           0,
		LocationReceived:     location != nil,
		LocationUsed:         false,
		CommonMatchedAliases: []string{},
		NeedsMoreInformation: []string{},
		DiscoveryStatus:      "NOT_STORED",
		OutageState:          OutageState,
	}
	if q == "" {
		return result
	}

	type internalMatch struct {
		place   Place
		aliases []string
	}
	matches := []internalMatch{}
	for _, place := range defaultPlaceGazetteer.Places {
		matched := []string{}
		for _, alias := range place.NormalizedAliases {
			alias = strings.TrimSpace(alias)
			if alias == "" {
				continue
			}
			if utf8.RuneCountInString(alias) < 3 && q != alias {
				continue
			}
			if strings.Contains(q, alias) {
				matched = append(matched, alias)
			}
		}
		if len(matched) > 0 {
			sort.Strings(matched)
			matches = append(matches, internalMatch{place: place, aliases: uniqueStrings(matched)})
		}
	}

	if len(matches) == 0 {
		result.NeedsMoreInformation = []string{"exact_place_name_or_shared_location"}
		return result
	}

	common := append([]string{}, matches[0].aliases...)
	for _, m := range matches[1:] {
		common = intersectStrings(common, m.aliases)
	}
	sort.Strings(common)
	result.CommonMatchedAliases = common

	public := make([]PlaceMatch, 0, len(matches))
	for _, m := range matches {
		public = append(public, publicPlaceMatch(m.place, m.aliases))
	}
	sort.Slice(public, func(i, j int) bool {
		li := longestAlias(public[i].MatchedAliases)
		lj := longestAlias(public[j].MatchedAliases)
		if li != lj {
			return li > lj
		}
		if public[i].CanonicalName != public[j].CanonicalName {
			return public[i].CanonicalName < public[j].CanonicalName
		}
		return public[i].PlaceID < public[j].PlaceID
	})
	if len(public) > limit {
		public = public[:limit]
	}
	result.Matches = public
	result.MatchCount = len(matches)

	if len(matches) == 1 {
		result.Status = "MATCHED_SINGLE_PLACE"
		selected := publicPlaceMatch(matches[0].place, matches[0].aliases)
		if location != nil && matches[0].place.Location != nil {
			d := haversineMeters(location.Lat, location.Lon, matches[0].place.Location.Lat, matches[0].place.Location.Lon)
			selected.ApproxDistanceM = float64Ptr(round1(d))
		}
		result.SelectedPlace = &selected
		return result
	}

	// GPS may disambiguate only when all candidates matched the same alias family.
	// Multiple independent place mentions must stay as multiple evidence, not be collapsed by location.
	if len(common) == 0 {
		result.Status = "MULTIPLE_PLACE_EVIDENCE"
		result.NeedsMoreInformation = []string{"clarify_target_place_if_single_selection_is_required"}
		return result
	}

	if location != nil && locationUsableForPlace(location) {
		located := make([]PlaceMatch, 0, len(matches))
		allLocated := true
		for _, m := range matches {
			if m.place.Location == nil {
				allLocated = false
				break
			}
			pm := publicPlaceMatch(m.place, m.aliases)
			d := haversineMeters(location.Lat, location.Lon, m.place.Location.Lat, m.place.Location.Lon)
			pm.ApproxDistanceM = float64Ptr(round1(d))
			located = append(located, pm)
		}
		if allLocated {
			sort.Slice(located, func(i, j int) bool {
				return *located[i].ApproxDistanceM < *located[j].ApproxDistanceM
			})
			closest := *located[0].ApproxDistanceM
			second := math.Inf(1)
			if len(located) > 1 {
				second = *located[1].ApproxDistanceM
			}
			margin := 75.0
			if location.AccuracyM != nil && *location.AccuracyM*2 > margin {
				margin = *location.AccuracyM * 2
			}
			if closest <= 500 && second-closest >= margin {
				selected := located[0]
				result.Status = "MATCHED_SINGLE_PLACE_BY_LOCATION"
				result.SelectedPlace = &selected
				result.LocationUsed = true
				result.Matches = located
				if len(result.Matches) > limit {
					result.Matches = result.Matches[:limit]
				}
				return result
			}
			result.Matches = located
			if len(result.Matches) > limit {
				result.Matches = result.Matches[:limit]
			}
		}
	}

	result.Status = "AMBIGUOUS_PLACE"
	result.NeedsMoreInformation = []string{"exact_branch_or_shared_location"}
	return result
}

func publicPlaceMatch(place Place, matched []string) PlaceMatch {
	return PlaceMatch{
		PlaceID:         place.PlaceID,
		CanonicalName:   place.CanonicalName,
		Aliases:         append([]string{}, place.Aliases...),
		PlaceType:       place.PlaceType,
		PlaceKind:       place.PlaceKind,
		Scope:           place.Scope,
		Location:        place.Location,
		Sources:         append([]PlaceSource{}, place.Sources...),
		Topology:        publicPlaceTopology(place.Topology),
		Validation:      place.Validation,
		MatchedAliases:  append([]string{}, matched...),
	}
}

func publicPlaceTopology(topology PlaceTopology) PlaceTopology {
	out := topology
	out.TransformerCandidates = append([]PlaceTransformerCandidate{}, topology.TransformerCandidates...)
	for i := range out.TransformerCandidates {
		candidate := &out.TransformerCandidates[i]
		if operational, ok := transformerOperationalAsset(candidate.FacilityID); ok {
			candidate.DownstreamMeterCount = operational.DownstreamMeterCount
			candidate.PotentialImpactSemantics = "DOWNSTREAM_METER_COUNT_IF_THIS_TRANSFORMER_IS_CONFIRMED_OUT"
			route := operational.RouteFromPEABuengKan
			candidate.RouteFromPEABuengKan = &route
		}
	}
	return out
}

func normalizePlaceSearch(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	value = strings.NewReplacer("\u200b", "", "\u200c", "", "\u200d", "", "\ufeff", "", "เเสน", "แสน").Replace(value)
	var b strings.Builder
	for _, r := range value {
		if unicode.IsSpace(r) || strings.ContainsRune("-_/.,()[]{}:;", r) {
			continue
		}
		b.WriteRune(r)
	}
	return b.String()
}

func locationUsableForPlace(location *PlaceResolveLocationInput) bool {
	if location == nil || location.Lat < -90 || location.Lat > 90 || location.Lon < -180 || location.Lon > 180 {
		return false
	}
	return location.AccuracyM == nil || (*location.AccuracyM >= 0 && *location.AccuracyM <= 150)
}

func haversineMeters(lat1, lon1, lat2, lon2 float64) float64 {
	const radius = 6371000.0
	p1 := lat1 * math.Pi / 180
	p2 := lat2 * math.Pi / 180
	dp := (lat2 - lat1) * math.Pi / 180
	dl := (lon2 - lon1) * math.Pi / 180
	a := math.Sin(dp/2)*math.Sin(dp/2) + math.Cos(p1)*math.Cos(p2)*math.Sin(dl/2)*math.Sin(dl/2)
	return 2 * radius * math.Asin(math.Sqrt(a))
}

func intersectStrings(a, b []string) []string {
	set := map[string]bool{}
	for _, value := range b {
		set[value] = true
	}
	out := []string{}
	for _, value := range a {
		if set[value] {
			out = append(out, value)
		}
	}
	return uniqueStrings(out)
}

func uniqueStrings(values []string) []string {
	seen := map[string]bool{}
	out := []string{}
	for _, value := range values {
		if value != "" && !seen[value] {
			seen[value] = true
			out = append(out, value)
		}
	}
	return out
}

func longestAlias(values []string) int {
	best := 0
	for _, value := range values {
		if n := utf8.RuneCountInString(value); n > best {
			best = n
		}
	}
	return best
}

func round1(value float64) float64 { return math.Round(value*10) / 10 }
func float64Ptr(value float64) *float64 { return &value }
