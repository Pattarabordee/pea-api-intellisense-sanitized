const baseUrl = (process.env.BUENGKAN_API_BASE_URL || process.env.API_BASE_URL || "http://127.0.0.1:8090").replace(/\/$/, "");
const apiKey = process.env.OUTAGE_INTEGRATION_API_KEY || process.env.AIS_INBOUND_API_KEY || "";

if (!apiKey) {
  console.error("OUTAGE_INTEGRATION_API_KEY or AIS_INBOUND_API_KEY is required");
  process.exit(2);
}

const eventId = `smoke-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const body = {
  schema_version: "outage-report.v1",
  source: {
    channel: "N8N",
    event_id: eventId,
    occurred_at: new Date().toISOString(),
    reporter_ref: "usr_smoke_ref",
    conversation_ref: "conv_smoke_ref"
  },
  message: { text: "บ้านแสนประเสริฐ ซอยเทคนิค ไฟดับ" },
  location: { lat: 1.234567, lon: 2.345678, accuracy_m: 10, source: "synthetic_smoke" }
};

async function api(path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    cache: "no-store",
    headers: {
      ...(options.headers || {}),
      "X-API-Key": apiKey
    }
  });
  const data = await response.json().catch(() => ({}));
  return { response, data };
}

const created = await api("/api/v1/outage-reports/resolve", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body)
});
if (created.response.status !== 201) {
  throw new Error(`resolve expected 201, got ${created.response.status}: ${JSON.stringify(created.data)}`);
}
const resolution = created.data.resolution || {};
const selected = resolution.selected_transformers || [];
if (
  resolution.status !== "RESOLVED_FOOTPRINT" ||
  resolution.selected_feeder !== "BUA04" ||
  selected.length !== 1 ||
  selected[0].facility_id !== "67-006308" ||
  !selected[0].location?.lat ||
  !selected[0].location?.lon ||
  selected[0].location?.crs !== "EPSG:4326" ||
  selected[0].outage_state !== "UNDETERMINED" ||
  created.data.mode !== "shadow" ||
  created.data.production_send !== "blocked"
) {
  throw new Error(`unexpected resolve result: ${JSON.stringify(created.data)}`);
}
if (JSON.stringify(created.data).includes("1.234567") || JSON.stringify(created.data).includes("2.345678")) {
  throw new Error("response echoed inbound user location");
}

const requestId = created.data.request_id;
const lookup = await api(`/api/v1/outage-topology/results/${encodeURIComponent(requestId)}`);
if (!lookup.response.ok || lookup.data.request_id !== requestId || lookup.data.resolution?.selected_transformers?.[0]?.facility_id !== "67-006308") {
  throw new Error(`result lookup failed: ${lookup.response.status} ${JSON.stringify(lookup.data)}`);
}

const asset = await api("/api/v1/transformers/67-006308");
if (
  !asset.response.ok ||
  asset.data.asset?.facility_id !== "67-006308" ||
  asset.data.asset?.asset_id_type !== "PEA_GIS_FACILITYID" ||
  !asset.data.asset?.location?.lat ||
  !asset.data.asset?.location?.lon ||
  asset.data.asset?.location?.crs !== "EPSG:4326"
) {
  throw new Error(`transformer lookup failed: ${asset.response.status} ${JSON.stringify(asset.data)}`);
}
if (JSON.stringify(asset.data).toLowerCase().includes("peano")) {
  throw new Error("transformer lookup exposed PEANO field");
}

const duplicate = await api("/api/v1/outage-reports/resolve", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body)
});
if (!duplicate.response.ok || duplicate.data.request_id !== requestId || duplicate.data.duplicate !== true) {
  throw new Error(`idempotency failed: ${duplicate.response.status} ${JSON.stringify(duplicate.data)}`);
}

console.log(JSON.stringify({
  status: "PASS",
  baseUrl,
  requestId,
  resolve: "PASS",
  durableResultLookup: "PASS",
  transformerCoordinates: "PASS",
  idempotency: "PASS",
  privacy: "PASS",
  mode: "shadow",
  production_send: "blocked"
}));
