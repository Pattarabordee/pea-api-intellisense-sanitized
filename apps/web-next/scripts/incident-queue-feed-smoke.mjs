import http from "node:http";
import { spawn } from "node:child_process";

const upstreamPort = 3198;
const now = "2026-09-01T15:55:00+07:00";

const liveFeed = {
  schema_version: "incident-queue-feed.v1",
  mode: "shadow",
  production_send: "blocked",
  authoritative_outage_truth: false,
  generated_at: now,
  source_id: "synthetic-read-only-feed",
  snapshot: {
    schema_version: "incident-priority.v1",
    generated_at: now,
    mode: "shadow",
    production_send: "blocked",
    source: "priority_adapter_composed",
    items: [
      {
        incident_id: "INC-BKN-FEED-SMOKE-001",
        area: "BKN",
        area_label: "บึงกาฬ",
        queue_rank: 1,
        priority_score: 40,
        raw_priority_score: null,
        score_max: null,
        priority_level: "HIGH",
        priority_state: "AVAILABLE",
        event_type: "SYNTHETIC_FEED_TEST",
        transformer_id: "SYNTHETIC-TX-001",
        feeder_id: "SYNTHETIC-FDR-01",
        affected_customers: 12,
        report_count: 4,
        critical_customer_risk: "synthetic only",
        evidence_strength: "MODERATE",
        first_reported_at: now,
        waiting_minutes: 3,
        status: "NEW",
        ai_summary: "Synthetic read-only feed contract test.",
        priority_reasons: ["synthetic priority signal"],
        evidence_chain: ["synthetic incident", "priority adapter contract"],
        source_mode: "PRIORITY_ADAPTER"
      }
    ]
  }
};

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) });
  res.end(payload);
}

const upstream = http.createServer((req, res) => {
  if (req.url === "/live") {
    if (req.headers["x-api-key"] !== "synthetic-test-key") return json(res, 401, { error: "missing test key" });
    return json(res, 200, liveFeed);
  }
  if (req.url === "/invalid") {
    return json(res, 200, { ...liveFeed, production_send: "enabled" });
  }
  return json(res, 503, { error: "synthetic unavailable" });
});

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(url) {
  let lastError;
  for (let i = 0; i < 50; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await delay(100);
  }
  throw lastError || new Error(`server not ready: ${url}`);
}

async function stopChild(child) {
  if (child.exitCode !== null) return;
  child.kill();
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    delay(1500)
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

async function runCase({ port, path, expectedStatus, expectedFallback, expectedItem, expectPageText, apiKey = false }) {
  const env = { ...process.env, PORT: String(port), HOSTNAME: "127.0.0.1" };
  delete env.INCIDENT_QUEUE_FEED_URL;
  delete env.INCIDENT_QUEUE_FEED_API_KEY;
  if (path) env.INCIDENT_QUEUE_FEED_URL = `http://127.0.0.1:${upstreamPort}${path}`;
  if (apiKey) env.INCIDENT_QUEUE_FEED_API_KEY = "synthetic-test-key";

  const child = spawn(process.execPath, [".next/standalone/server.js"], {
    cwd: process.cwd(),
    env,
    stdio: ["ignore", "pipe", "pipe"]
  });

  try {
    await waitFor(`http://127.0.0.1:${port}/api/incidents/feed`);
    const response = await fetch(`http://127.0.0.1:${port}/api/incidents/feed`);
    const body = await response.json();
    assert(response.status === 200, `feed endpoint ${port} should return 200`);
    assert(body.source_health.status === expectedStatus, `${port}: expected ${expectedStatus}, got ${body.source_health.status}`);
    assert(body.source_health.fallback_active === expectedFallback, `${port}: fallback mismatch`);
    if (expectedItem) {
      assert(body.snapshot.items[0]?.incident_id === expectedItem, `${port}: live item not preserved`);
      assert(body.snapshot.items[0]?.report_count === 4, `${port}: report_count must survive feed normalization`);
    }
    if (expectedFallback) assert(body.snapshot.source === "synthetic_demo", `${port}: fallback must be visibly synthetic`);

    const page = await (await fetch(`http://127.0.0.1:${port}/incident-priority`)).text();
    assert(page.includes(expectPageText), `${port}: page source-health indicator missing ${expectPageText}`);
    assert(page.includes("e-Response") && page.includes("เหตุการณ์ทั้งหมด"), `${port}: e-Response Event Management framing missing`);
    assert(page.includes("ใช้เงื่อนไขที่กำหนดไว้"), `${port}: native e-Response condition control missing`);
    assert(page.includes("AI PRIORITY") && page.includes("SHADOW · READ ONLY"), `${port}: additive AI Priority read-only framing missing`);
    if (expectedItem) {
      assert(page.includes("BKN #1"), `${port}: area-scoped rank must remain visible`);
      assert(page.includes("รอแก้ไข"), `${port}: NEW event must use e-Response waiting status presentation`);
    }
  } finally {
    await stopChild(child);
  }
}

await new Promise((resolve) => upstream.listen(upstreamPort, "127.0.0.1", resolve));
try {
  await runCase({
    port: 3104,
    path: "/live",
    expectedStatus: "LIVE_SHADOW",
    expectedFallback: false,
    expectedItem: "INC-BKN-FEED-SMOKE-001",
    expectPageText: "เชื่อมข้อมูลจริง · SHADOW",
    apiKey: true
  });
  await runCase({
    port: 3105,
    path: "/invalid",
    expectedStatus: "CONTRACT_INVALID",
    expectedFallback: true,
    expectPageText: "ข้อมูลไม่ผ่านการตรวจสอบ"
  });
  await runCase({
    port: 3106,
    path: "/unavailable",
    expectedStatus: "UPSTREAM_UNAVAILABLE",
    expectedFallback: true,
    expectPageText: "แหล่งข้อมูลขัดข้อง"
  });
  await runCase({
    port: 3107,
    path: null,
    expectedStatus: "NOT_CONFIGURED",
    expectedFallback: true,
    expectPageText: "ยังไม่เชื่อมข้อมูล"
  });
} finally {
  upstream.close();
}

console.log("INCIDENT_QUEUE_FEED_SMOKE_PASS");
console.log(JSON.stringify({ cases: 4, contract: "incident-queue-feed.v1", mode: "server-side read-only pull", fallback: "synthetic-visible" }));
