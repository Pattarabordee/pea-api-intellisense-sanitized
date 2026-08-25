package buengkan

import "testing"

func ptrFloat64(v float64) *float64 { return &v }

func TestMatchLocationFindsTraceConfirmedDongMakYangTransformer(t *testing.T) {
	match := MatchLocation(LocationInput{
		Lat: 18.316689433697476,
		Lon: 103.71130803535446,
		AccuracyM: ptrFloat64(5),
		Source: "user_shared_location",
	})
	if match.Status != "GPS_SINGLE_TX_CANDIDATE" || len(match.Candidates) != 1 || match.Candidates[0].FacilityID != "63-006344" {
		t.Fatalf("unexpected GPS match: %#v", match)
	}
	if match.UsedForTopology {
		t.Fatalf("raw match must not claim use until fused with topology: %#v", match)
	}
}

func TestResolveWithLocationCanResolveGenericOutageText(t *testing.T) {
	result := ResolveWithLocation("ไฟดับ", &LocationInput{
		Lat: 18.316689433697476,
		Lon: 103.71130803535446,
		AccuracyM: ptrFloat64(5),
		Source: "user_shared_location",
	})
	if result.Status != "RESOLVED_GPS_FOOTPRINT" || len(result.SelectedTransformers) != 1 || result.SelectedTransformers[0].FacilityID != "63-006344" {
		t.Fatalf("generic GPS resolution failed: %#v", result)
	}
	if result.SelectedFeeder != "BUA03" || result.LocationEvidence == nil || !result.LocationEvidence.UsedForTopology {
		t.Fatalf("GPS evidence not applied safely: %#v", result)
	}
	if result.OutageState != OutageState {
		t.Fatalf("GPS must not confirm live outage: %#v", result)
	}
}

func TestResolveWithLocationNarrowsConsistentVillageInventory(t *testing.T) {
	result := ResolveWithLocation("บ้านแสนประเสริฐไฟดับ", &LocationInput{
		Lat: 18.35796008786873,
		Lon: 103.62435111585168,
		AccuracyM: ptrFloat64(5),
		Source: "user_shared_location",
	})
	if result.Status != "RESOLVED_GPS_FOOTPRINT" || len(result.SelectedTransformers) != 1 || result.SelectedTransformers[0].FacilityID != "67-006308" {
		t.Fatalf("village + GPS did not narrow correctly: %#v", result)
	}
	if result.VillageKey != "38-01-01-M09" || result.SelectedFeeder != "BUA04" {
		t.Fatalf("village context was lost: %#v", result)
	}
}

func TestResolveWithLocationFailsClosedOnVillageGPSConflict(t *testing.T) {
	result := ResolveWithLocation("บ้านแสนประเสริฐไฟดับ", &LocationInput{
		Lat: 18.316689433697476,
		Lon: 103.71130803535446,
		AccuracyM: ptrFloat64(5),
		Source: "user_shared_location",
	})
	if result.Status != "EVIDENCE_CONFLICT" || len(result.SelectedTransformers) != 0 || result.SelectedFeeder != "" {
		t.Fatalf("conflicting GPS must fail closed: %#v", result)
	}
	if result.LocationEvidence == nil || result.LocationEvidence.UsedForTopology {
		t.Fatalf("conflicting location must not be marked as used: %#v", result)
	}
}

func TestPoorAccuracyDoesNotChangeTextTopology(t *testing.T) {
	result := ResolveWithLocation("บ้านดงหมากยางไฟดับ", &LocationInput{
		Lat: 18.316689433697476,
		Lon: 103.71130803535446,
		AccuracyM: ptrFloat64(300),
		Source: "network_location",
	})
	if result.Status != "VILLAGE_ONLY_SINGLE_FEEDER" {
		t.Fatalf("poor GPS accuracy should not override text topology: %#v", result)
	}
	if result.LocationEvidence == nil || result.LocationEvidence.Status != "LOCATION_ACCURACY_TOO_LOW" || result.LocationEvidence.UsedForTopology {
		t.Fatalf("poor GPS accuracy guardrail missing: %#v", result)
	}
}

func TestExcludedVillageCannotBeOverriddenByGPS(t *testing.T) {
	result := ResolveWithLocation("บ้านท่าไคร้ไฟดับ", &LocationInput{
		Lat: 18.316689433697476,
		Lon: 103.71130803535446,
		AccuracyM: ptrFloat64(5),
		Source: "user_shared_location",
	})
	if result.Status != "UNSUPPORTED_VILLAGE" || result.Supported {
		t.Fatalf("GPS must not bypass excluded village gate: %#v", result)
	}
	if result.LocationEvidence == nil || result.LocationEvidence.UsedForTopology {
		t.Fatalf("excluded village GPS must remain unused: %#v", result)
	}
}
