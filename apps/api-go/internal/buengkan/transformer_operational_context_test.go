package buengkan

import "testing"

func TestTransformerOperationalContextCoversApprovedRegistry(t *testing.T) {
    if defaultTransformerOperationalContext.AssetCount != 95 || len(defaultTransformerOperationalContext.Assets) != 95 {
        t.Fatalf("expected 95 operational assets, got count=%d map=%d", defaultTransformerOperationalContext.AssetCount, len(defaultTransformerOperationalContext.Assets))
    }
    for facilityID := range defaultRegistry.TransformerCatalog {
        item, ok := defaultTransformerOperationalContext.Assets[facilityID]
        if !ok { t.Fatalf("missing operational context for %s", facilityID) }
        if item.DownstreamMeterCount == nil || *item.DownstreamMeterCount < 0 { t.Fatalf("missing downstream meter count for %s: %#v", facilityID, item) }
        if item.DownstreamMeterTraceStatus != "OK" { t.Fatalf("trace not OK for %s: %#v", facilityID, item) }
        route := item.RouteFromPEABuengKan
        if route.Status != "OK" || route.RoadDistanceKM == nil || route.EstimatedDriveMinutes == nil {
            t.Fatalf("missing route for %s: %#v", facilityID, route)
        }
        if *route.RoadDistanceKM < 0 || *route.EstimatedDriveMinutes < 1 { t.Fatalf("invalid route values for %s: %#v", facilityID, route) }
        if route.TrafficAware || route.GoogleMapsExact { t.Fatalf("OSRM snapshot must not claim live Google semantics: %#v", route) }
        if route.Origin.Lat != 18.323300448481316 || route.Origin.Lon != 103.63348560640729 { t.Fatalf("wrong PEA office origin: %#v", route.Origin) }
    }
}

func TestTransformerResultExposesPotentialImpactWithoutConfirmingOutage(t *testing.T) {
    asset, err := LookupTransformer("63-006344")
    if err != nil { t.Fatal(err) }
    tx := asset.Transformer
    if tx.DownstreamMeterCount == nil || *tx.DownstreamMeterCount != 135 { t.Fatalf("unexpected downstream count: %#v", tx) }
    if tx.PotentialImpactSemantics != "DOWNSTREAM_METER_COUNT_IF_THIS_TRANSFORMER_IS_CONFIRMED_OUT" { t.Fatalf("unsafe impact semantics: %#v", tx) }
    if tx.RouteFromPEABuengKan == nil || tx.RouteFromPEABuengKan.RoadDistanceKM == nil || *tx.RouteFromPEABuengKan.RoadDistanceKM <= 0 { t.Fatalf("missing route: %#v", tx) }
    if tx.OutageState != "UNDETERMINED" { t.Fatalf("static impact context must not confirm outage: %#v", tx) }
}
