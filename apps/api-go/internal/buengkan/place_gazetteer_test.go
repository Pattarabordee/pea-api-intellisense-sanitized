package buengkan

import "testing"

func TestPlaceGazetteerLoadsExpectedSeedsAndGuardrails(t *testing.T) {
	if PlaceGazetteerCount() != 104 {
		t.Fatalf("expected 104 places, got %d", PlaceGazetteerCount())
	}
	g := PlaceGazetteerGuardrails()
	if g["category_required_for_resolution"] != false || g["fuzzy_matching_enabled"] != false || g["unknown_place_auto_added"] != false {
		t.Fatalf("unexpected universal resolver guardrails: %#v", g)
	}
	if g["mode"] != Mode || g["production_send"] != ProductionSend {
		t.Fatalf("unsafe place gazetteer mode: %#v", g)
	}
}

func TestPlaceResolverSingleNamedPlace(t *testing.T) {
	result := ResolvePlace("ไฟดับหน้าโรงพยาบาลบึงกาฬ", nil, 10)
	if result.Status != "MATCHED_SINGLE_PLACE" || result.MatchCount != 1 || result.SelectedPlace == nil {
		t.Fatalf("expected one hospital place: %#v", result)
	}
	if result.SelectedPlace.CanonicalName != "โรงพยาบาลบึงกาฬ" {
		t.Fatalf("unexpected hospital: %#v", result.SelectedPlace)
	}
	if result.OutageState != OutageState || result.SelectedPlace.Topology.OutageState != OutageState {
		t.Fatalf("place resolution must not confirm outage: %#v", result)
	}
}

func TestPlaceResolverBrandOnlyIsAmbiguous(t *testing.T) {
	result := ResolvePlace("ไฟดับแถว 7-11", nil, 10)
	if result.Status != "AMBIGUOUS_PLACE" || result.MatchCount != 2 || result.SelectedPlace != nil {
		t.Fatalf("brand-only must fail closed: %#v", result)
	}
	if len(result.CommonMatchedAliases) == 0 {
		t.Fatalf("expected common 7-Eleven alias: %#v", result)
	}
}

func TestPlaceResolverSharedLocationDisambiguatesSameBrand(t *testing.T) {
	accuracy := 10.0
	result := ResolvePlace("ไฟดับแถว 7-Eleven", &PlaceResolveLocationInput{
		Lat: 18.364986, Lon: 103.652900, AccuracyM: &accuracy, Source: "user_shared_location",
	}, 10)
	if result.Status != "MATCHED_SINGLE_PLACE_BY_LOCATION" || !result.LocationUsed || result.SelectedPlace == nil {
		t.Fatalf("expected location disambiguation: %#v", result)
	}
	if result.SelectedPlace.CanonicalName != "เซเว่นอีเลฟเว่น" {
		t.Fatalf("expected PEA 7-Eleven location: %#v", result.SelectedPlace)
	}
	if len(result.SelectedPlace.Topology.TransformerCandidates) != 1 || result.SelectedPlace.Topology.TransformerCandidates[0].FacilityID != "65-006228" {
		t.Fatalf("expected existing LV candidate without promoting it: %#v", result.SelectedPlace.Topology)
	}
}

func TestPlaceResolverImpreciseLocationDoesNotDisambiguateBrand(t *testing.T) {
	accuracy := 300.0
	result := ResolvePlace("7-11", &PlaceResolveLocationInput{
		Lat: 18.364986, Lon: 103.652900, AccuracyM: &accuracy, Source: "user_shared_location",
	}, 10)
	if result.Status != "AMBIGUOUS_PLACE" || result.LocationUsed {
		t.Fatalf("imprecise GPS must not choose branch: %#v", result)
	}
}

func TestPlaceResolverMultipleIndependentPlacesRemainMultipleEvidence(t *testing.T) {
	accuracy := 10.0
	result := ResolvePlace("โรงพยาบาลบึงกาฬ ใกล้ตลาดสดสุขาภิบาลบึงกาฬ", &PlaceResolveLocationInput{
		Lat: 18.3656, Lon: 103.6532, AccuracyM: &accuracy, Source: "user_shared_location",
	}, 10)
	if result.Status != "MULTIPLE_PLACE_EVIDENCE" || result.MatchCount < 2 || result.LocationUsed || result.SelectedPlace != nil {
		t.Fatalf("independent place clues must not be collapsed: %#v", result)
	}
}

func TestPlaceResolverExcludedVillagePreservesFailClosedTopology(t *testing.T) {
	result := ResolvePlace("บ้านท่าไคร้ไฟดับ", nil, 10)
	if result.Status != "MATCHED_SINGLE_PLACE" || result.SelectedPlace == nil {
		t.Fatalf("expected village entity match: %#v", result)
	}
	if result.SelectedPlace.Validation.Status != "EXCLUDED_TOPOLOGY_GATE" || result.SelectedPlace.Topology.CandidateCount != 0 {
		t.Fatalf("excluded village must remain fail closed: %#v", result.SelectedPlace)
	}
}

func TestPlaceLookupReturnsSafePublicShape(t *testing.T) {
	resolved := ResolvePlace("โรงพยาบาลบึงกาฬ", nil, 10)
	if resolved.SelectedPlace == nil {
		t.Fatal("hospital place missing")
	}
	lookup, err := LookupPlace(resolved.SelectedPlace.PlaceID)
	if err != nil {
		t.Fatalf("lookup failed: %v", err)
	}
	if lookup.PlaceID != resolved.SelectedPlace.PlaceID || len(lookup.MatchedAliases) != 0 {
		t.Fatalf("unexpected lookup result: %#v", lookup)
	}
}
