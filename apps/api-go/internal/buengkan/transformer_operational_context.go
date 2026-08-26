package buengkan

import (
    _ "embed"
    "encoding/json"
)

//go:embed data/transformer_operational_context_v1.json
var transformerOperationalContextJSON []byte

const TransformerOperationalContextVersion = "transformer-operational-context.v1"

type TransformerRouteOrigin struct {
    Name string `json:"name"`
    Lat float64 `json:"lat"`
    Lon float64 `json:"lon"`
    CRS string `json:"crs"`
}

type TransformerRoute struct {
    Status string `json:"status"`
    RoadDistanceKM *float64 `json:"road_distance_km,omitempty"`
    EstimatedDriveMinutes *int `json:"estimated_drive_minutes,omitempty"`
    DurationSeconds *int `json:"duration_seconds,omitempty"`
    Origin TransformerRouteOrigin `json:"origin"`
    RoutingSource string `json:"routing_source"`
    RoutingMethod string `json:"routing_method"`
    TrafficAware bool `json:"traffic_aware"`
    GoogleMapsExact bool `json:"google_maps_exact"`
}

type TransformerOperationalAsset struct {
    FacilityID string `json:"facility_id"`
    FeederID string `json:"feeder_id"`
    DownstreamMeterCount *int `json:"downstream_meter_count"`
    DownstreamMeterCountSource string `json:"downstream_meter_count_source"`
    DownstreamMeterTraceStatus string `json:"downstream_meter_trace_status"`
    GISNumberOfUser *int `json:"gis_number_of_user"`
    RouteFromPEABuengKan TransformerRoute `json:"route_from_pea_buengkan"`
}

type transformerOperationalContext struct {
    SchemaVersion string `json:"schema_version"`
    AssetCount int `json:"asset_count"`
    Assets map[string]TransformerOperationalAsset `json:"assets"`
    Guardrails map[string]any `json:"guardrails"`
}

var defaultTransformerOperationalContext = mustLoadTransformerOperationalContext()

func mustLoadTransformerOperationalContext() transformerOperationalContext {
    var data transformerOperationalContext
    if err := json.Unmarshal(transformerOperationalContextJSON, &data); err != nil { panic(err) }
    if data.SchemaVersion != TransformerOperationalContextVersion { panic("unexpected transformer operational context version") }
    if data.AssetCount != 95 { panic("transformer operational context asset count mismatch") }
    if mode, _ := data.Guardrails["mode"].(string); mode != Mode { panic("transformer operational context mode mismatch") }
    if send, _ := data.Guardrails["production_send"].(string); send != ProductionSend { panic("transformer operational context production_send mismatch") }
    return data
}

func transformerOperationalAsset(facilityID string) (TransformerOperationalAsset, bool) {
    item, ok := defaultTransformerOperationalContext.Assets[facilityID]
    return item, ok
}
