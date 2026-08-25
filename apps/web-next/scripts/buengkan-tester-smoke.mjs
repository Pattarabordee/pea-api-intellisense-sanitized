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
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  return { response, body };
}

const wrong = await resolve("บ้านดงหมากยางไฟดับ", "INVALID-CODE");
if (wrong.response.status !== 401) {
  throw new Error(`expected invalid access code to return 401, got ${wrong.response.status}`);
}

const cases = [
  {
    text: "บ้านดงหมากยางไฟดับ",
    status: "VILLAGE_ONLY_SINGLE_FEEDER",
    feeder: "BUA03",
    transformers: ["63-006344"]
  },
  {
    text: "บ้านแสนประเสริฐ ซอยเทคนิค ไฟดับ",
    status: "RESOLVED_FOOTPRINT",
    feeder: "BUA04",
    transformers: ["67-006308"]
  },
  {
    text: "บ้านบึงสวรรค์ไฟดับ",
    status: "UNSUPPORTED_VILLAGE",
    feeder: null,
    transformers: []
  },
  {
    text: "บ้านแสนประเสริฐ แถวบิ๊กเสือไฟดับ",
    status: "AMBIGUOUS_FOOTPRINT",
    feeder: null,
    transformers: []
  }
];

for (const item of cases) {
  const { response, body } = await resolve(item.text);
  if (!response.ok) throw new Error(`${item.text}: HTTP ${response.status}`);
  const actualTransformers = body.selectedTransformerCandidates || [];
  const ok =
    body.status === item.status &&
    (body.selectedFeeder ?? null) === item.feeder &&
    JSON.stringify(actualTransformers) === JSON.stringify(item.transformers) &&
    body.mode === "shadow" &&
    body.production_send === "blocked" &&
    body.outageLevel === "UNDETERMINED";
  if (!ok) {
    throw new Error(`${item.text}: unexpected resolver payload ${JSON.stringify(body)}`);
  }
}

const page = await fetch(`${baseUrl}/buengkan-tester`, { cache: "no-store" });
if (!page.ok || !(await page.text()).includes("Bueng Kan GIS Tester")) {
  throw new Error(`tester page failed: HTTP ${page.status}`);
}

console.log(JSON.stringify({
  status: "PASS",
  baseUrl,
  canonicalCases: cases.length,
  accessGate: "PASS",
  mode: "shadow",
  production_send: "blocked"
}));
