const baseUrl = (process.env.BUENGKAN_TESTER_BASE_URL || "http://127.0.0.1:3100").replace(/\/$/, "");
const accessCode = process.env.BUENGKAN_TESTER_ACCESS_CODE || "";

if (!accessCode) {
  console.error("BUENGKAN_TESTER_ACCESS_CODE is required");
  process.exit(2);
}

async function resolve(text, code = accessCode) {
  const response = await fetch(`${baseUrl}/api/buengkan/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({ accessCode: code, text })
  });
  let body = {};
  try { body = await response.json(); } catch { body = {}; }
  return { response, body };
}

const wrong = await resolve("บ้านดงหมากยางไฟดับ", "INVALID-CODE");
if (wrong.response.status !== 401) {
  throw new Error(`expected invalid access code to return 401, got ${wrong.response.status}`);
}

const cases = [
  { text: "บ้านศรีโสภณไฟดับ", status: "VILLAGE_ONLY_SINGLE_FEEDER", feeder: "BUB07", selected: 4, core: 4 },
  { text: "บ้านบึงกาฬใต้ไฟดับ", status: "VILLAGE_ONLY_MULTI_FEEDER", feeder: null, selected: 0, core: 8 },
  { text: "บ้านนาโนนไฟดับ", status: "VILLAGE_ONLY_MULTI_FEEDER", feeder: null, selected: 0, core: 18 },
  { text: "บ้านท่าโพธิ์ไฟดับ", status: "VILLAGE_ONLY_MULTI_FEEDER", feeder: null, selected: 0, core: 9 },
  { text: "บ้านดงหมากยางไฟดับ", status: "VILLAGE_ONLY_SINGLE_FEEDER", feeder: "BUA03", selected: 1, core: 1 },
  { text: "บ้านแสนประเสริฐไฟดับ", status: "VILLAGE_ONLY_MULTI_FEEDER", feeder: null, selected: 0, core: 18 },
  { text: "บ้านแสนสุขไฟดับ", status: "VILLAGE_ONLY_MULTI_FEEDER", feeder: null, selected: 0, core: 13 },
  { text: "บ้านแสนประเสริฐ ซอยเทคนิค ไฟดับ", status: "RESOLVED_FOOTPRINT", feeder: "BUA04", selected: 1, selectedIds: ["67-006308"], core: 18 },
  { text: "บ้านบึงสวรรค์ไฟดับ", status: "VILLAGE_ONLY_MULTI_FEEDER", feeder: null, selected: 0, core: 19 },
  { text: "บ้านแสนสำราญไฟดับ", status: "VILLAGE_ONLY_MULTI_FEEDER", feeder: null, selected: 0, core: 21 },
  { text: "บ้านท่าไคร้ไฟดับ", status: "UNSUPPORTED_VILLAGE", feeder: null, selected: 0, core: 0 }
];

for (const item of cases) {
  const { response, body } = await resolve(item.text);
  if (!response.ok) throw new Error(`${item.text}: HTTP ${response.status}`);
  const selected = body.selectedTransformerCandidates || [];
  const core = body.villageTransformerCandidates || [];
  const selectedDetails = body.selectedTransformerDetails || [];
  const coreDetails = body.villageTransformerDetails || [];
  const grouped = (body.villageTransformerGroups || []).flatMap((group) => group.transformers || []);
  const coordsOk = coreDetails.length === item.core && coreDetails.every((tx) => Number(tx.lat) !== 0 && Number(tx.lon) !== 0 && tx.crs === "EPSG:4326");
  const selectedCoordsOk = selectedDetails.length === item.selected && selectedDetails.every((tx) => Number(tx.lat) !== 0 && Number(tx.lon) !== 0);
  const ok =
    body.status === item.status &&
    (body.selectedFeeder ?? null) === item.feeder &&
    selected.length === item.selected &&
    core.length === item.core &&
    coordsOk &&
    selectedCoordsOk &&
    new Set(grouped).size === item.core &&
    (!item.selectedIds || JSON.stringify(selected) === JSON.stringify(item.selectedIds)) &&
    body.mode === "shadow" &&
    body.production_send === "blocked" &&
    body.outageLevel === "UNDETERMINED";
  if (!ok) throw new Error(`${item.text}: unexpected resolver payload ${JSON.stringify(body)}`);
}

const page = await fetch(`${baseUrl}/buengkan-tester`, { cache: "no-store" });
const pageText = await page.text();
if (!page.ok || !pageText.includes("BUENG KAN / GIS TESTER")) {
  throw new Error(`tester page failed: HTTP ${page.status}`);
}

console.log(JSON.stringify({
  status: "PASS",
  baseUrl,
  canonicalCases: cases.length,
  traceConfirmedVillageTxGate: "PASS",
  transformerCoordinateGate: "PASS",
  accessGate: "PASS",
  mode: "shadow",
  production_send: "blocked"
}));
