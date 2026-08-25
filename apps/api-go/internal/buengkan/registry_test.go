package buengkan

import "testing"

func TestRegistryHasCoordinatesForAllApprovedTransformers(t *testing.T) {
	if len(defaultRegistry.TransformerCatalog) != 95 {
		t.Fatalf("expected 95 approved transformers, got %d", len(defaultRegistry.TransformerCatalog))
	}
	for id, tx := range defaultRegistry.TransformerCatalog {
		if tx.FacilityID != id || tx.FeederID == "" || tx.Lat == 0 || tx.Lon == 0 || tx.CRS != "EPSG:4326" || tx.Source != "PEA_GIS_LAYER17" {
			t.Fatalf("invalid transformer catalog entry %s: %#v", id, tx)
		}
	}
}

func TestVillageOnlyReturnsServiceInventoryNotOutageConfirmation(t *testing.T) {
	result := Resolve("บ้านแสนสำราญไฟดับ")
	if result.Status != "VILLAGE_ONLY_MULTI_FEEDER" || len(result.ServiceInventory) != 21 || len(result.SelectedTransformers) != 0 {
		t.Fatalf("unexpected village inventory result: %#v", result)
	}
	if result.CandidateScope != "VILLAGE_SERVICE_INVENTORY" || result.OutageState != "UNDETERMINED" {
		t.Fatalf("unsafe candidate semantics: %#v", result)
	}
	feeders := map[string]bool{}
	for _, tx := range result.ServiceInventory {
		feeders[tx.FeederID] = true
		if tx.Location.CRS != "EPSG:4326" || tx.Location.Lat == 0 || tx.Location.Lon == 0 {
			t.Fatalf("missing transformer coordinates: %#v", tx)
		}
	}
	if len(feeders) != 6 {
		t.Fatalf("expected six service feeders, got %#v", feeders)
	}
}

func TestLandmarkNarrowsTransformerWithCoordinates(t *testing.T) {
	result := Resolve("บ้านแสนประเสริฐ ซอยเทคนิค ไฟดับ")
	if result.Status != "RESOLVED_FOOTPRINT" || result.SelectedFeeder != "BUA04" || len(result.SelectedTransformers) != 1 {
		t.Fatalf("unexpected narrowed result: %#v", result)
	}
	tx := result.SelectedTransformers[0]
	if tx.FacilityID != "67-006308" || tx.Location.Lat == 0 || tx.Location.Lon == 0 || tx.CandidateScope != "NARROWED_FOOTPRINT" {
		t.Fatalf("unexpected narrowed transformer: %#v", tx)
	}
	if tx.OutageState != "UNDETERMINED" {
		t.Fatalf("GIS candidate must not confirm live outage: %#v", tx)
	}
}

func TestExcludedVillageFailsClosed(t *testing.T) {
	result := Resolve("บ้านท่าไคร้ไฟดับ")
	if result.Status != "UNSUPPORTED_VILLAGE" || result.Supported || len(result.ServiceInventory) != 0 {
		t.Fatalf("excluded village did not fail closed: %#v", result)
	}
}

func TestTransformerLookupReturnsServiceVillages(t *testing.T) {
	asset, err := LookupTransformer("63-006344")
	if err != nil {
		t.Fatal(err)
	}
	if asset.Transformer.FacilityID != "63-006344" || asset.Transformer.Location.Lat == 0 || asset.Transformer.Location.Lon == 0 {
		t.Fatalf("bad asset lookup: %#v", asset)
	}
	if len(asset.ServiceVillages) != 2 {
		t.Fatalf("expected cross-village service mapping, got %#v", asset.ServiceVillages)
	}
}
