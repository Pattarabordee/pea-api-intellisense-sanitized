import http from "node:http";
import { spawn } from "node:child_process";

const upstreamPort = 3199;
const now = "2026-09-01T16:50:00+07:00";

const safeIncidentSource = {
  schema_version: "pea-incident-aggregate-source.v0.1",
  mode: "shadow",
  production_send: "blocked",
  authoritative_outage_truth: false,
  generated_at: now,
  source_id: "synthetic-aggregate-source",
  items: [
    {
      incident_id: "INC-BKN-CANDIDATE-001",
      area: "BKN",
      area_label: "บึงกาฬ",
      transformer_id: "63-006344",
      feeder_id: "BUA03",
      affected_customers: null,
      report_count: 2,
      critical_customer_risk: "NOT_EVALUATED",
      evidence_strength: "MODERATE",
      first_reported_at: now,
      waiting_minutes: 4,
      status: "NEW",
      event_type: "SYNTHETIC_OUTAGE_REPORT_CLUSTER",
      ai_summary: "Synthetic projection smoke only.",
      priority_reasons: ["synthetic evidence"],
      evidence_chain: ["synthetic incident cluster"]
    }
  ]
};

const sensitiveIncidentSource = {
  ...safeIncidentSource,
  items: [{ ...safeIncidentSource.items[0], customer_phone: "0812345678" }]
};

function priority(area) {
  return {
    mode: "shadow",
    production_send: "blocked",
    purpose: "decision_support_only",
    authoritative_outage_truth: false,
    schema_version: "priority-adapter-v0.1",
    adapter_status: "ok",
    ticket_id: `SYNTH-${area}`,
    service_area: area,
    queue_count: 1,
    queues: [
      {
        queue_rank: 1,
        transformer_id: area === "BKN" ? "63-006344" : "PKN-TX-SYNTHETIC",
        feeder_code: area === "BKN" ? "BUA03" : "PKN-SYNTHETIC",
        event_type: "Synthetic",
        event_status: "shadow",
        priority_score: area === "BKN" ? 4 : 7,
        raw_priority_score: null,
        score_max: 10,
        priority_level: "HIGH",
        ai_summary: "Synthetic priority snapshot smoke.",
        source: "synthetic"
      }
    ]
  };
}

function n8nExecution(id, stoppedAt, payload) {
  return {
    id,
    workflowId: "PEAPriorityAdapterV01",
    status: "success",
    stoppedAt,
    data: {
      resultData: {
        runData: {
          "Normalize Priority Result": [
            { data: { main: [[{ json: payload }]] } }
          ]
        }
      }
    }
  };
}

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) });
  res.end(payload);
}

const upstream = http.createServer((req, res) => {
  if (req.url?.startsWith("/api/v1/executions")) {
    if (req.headers["x-n8n-api-key"] !== "n8n-read-test-key") return json(res, 401, { error: "missing n8n api key" });
    const fresh = new Date().toISOString();
    const stale = new Date(Date.now() - 60 * 60 * 1000).toISOString();
    return json(res, 200, {
      data: [n8nExecution("n8n-fresh-bkn", fresh, priority("BKN")), n8nExecution("n8n-stale-pkn", stale, priority("PKN"))],
      nextCursor: null
    });
  }

  if (req.headers["x-api-key"] !== "upstream-test-key") return json(res, 401, { error: "missing upstream test key" });
  if (req.url === "/incident-safe") return json(res, 200, safeIncidentSource);
  if (req.url === "/incident-sensitive") return json(res, 200, sensitiveIncidentSource);
  if (req.url === "/priority-bkn") return json(res, 200, priority("BKN"));
  if (req.url === "/priority-pkn") return json(res, 200, priority("PKN"));
  if (req.url === "/priority-mismatch") return json(res, 200, priority("PKN"));
  return json(res, 503, { error: "synthetic unavailable" });
});

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(url, headers = {}) {
  let lastError;
  for (let i = 0; i < 60; i += 1) {
    try {
      const response = await fetch(url, { headers });
      if (response.status >= 100) return;
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
  await Promise.race([new Promise((resolve) => child.once("exit", resolve)), delay(1500)]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

async function runServer(port, envOverrides, testFn) {
  const env = { ...process.env, PORT: String(port), HOSTNAME: "127.0.0.1", ...envOverrides };
  const child = spawn(process.execPath, [".next/standalone/server.js"], { cwd: process.cwd(), env, stdio: ["ignore", "pipe", "pipe"] });
  try {
    await waitFor(`http://127.0.0.1:${port}/api/incidents/evidence-projection`);
    await testFn(port);
  } finally {
    await stopChild(child);
  }
}

await new Promise((resolve) => upstream.listen(upstreamPort, "127.0.0.1", resolve));
try {
  await runServer(3120, { SHADOW_CANDIDATE_ENDPOINTS_ENABLED: "false" }, async (port) => {
    const r = await fetch(`http://127.0.0.1:${port}/api/incidents/evidence-projection`);
    assert(r.status === 503, "candidate endpoints must be disabled by default");
  });

  await runServer(3121, {
    SHADOW_CANDIDATE_ENDPOINTS_ENABLED: "true",
    SHADOW_CANDIDATE_ENDPOINT_API_KEY: "candidate-test-key",
    INCIDENT_EVIDENCE_PROJECTION_SOURCE_URL: `http://127.0.0.1:${upstreamPort}/incident-safe`,
    INCIDENT_EVIDENCE_PROJECTION_SOURCE_API_KEY: "upstream-test-key",
    PRIORITY_SNAPSHOT_BKN_SOURCE_URL: `http://127.0.0.1:${upstreamPort}/priority-bkn`,
    PRIORITY_SNAPSHOT_BKN_SOURCE_API_KEY: "upstream-test-key"
  }, async (port) => {
    const unauthorized = await fetch(`http://127.0.0.1:${port}/api/incidents/evidence-projection`);
    assert(unauthorized.status === 401, "candidate endpoint auth must fail closed when configured");

    const headers = { "X-API-Key": "candidate-test-key" };
    const evidenceResponse = await fetch(`http://127.0.0.1:${port}/api/incidents/evidence-projection`, { headers });
    const evidence = await evidenceResponse.json();
    assert(evidenceResponse.status === 200, "safe incident projection should return 200");
    assert(evidence.schema_version === "pea-incident-evidence.v1", "projection must emit canonical evidence schema");
    assert(evidence.items?.[0]?.incident_id === "INC-BKN-CANDIDATE-001", "projection must preserve safe incident identity");
    assert(!("customer_phone" in evidence.items[0]), "projection must not emit customer phone");
    assert(evidence.items[0].affected_customers === null && evidence.items[0].report_count === 2, "unknown affected-customer count must remain separate from report_count");

    const priorityResponse = await fetch(`http://127.0.0.1:${port}/api/priority-adapter/snapshot?area=BKN`, { headers });
    const snapshot = await priorityResponse.json();
    assert(priorityResponse.status === 200, "BKN priority wrapper should return 200");
    assert(snapshot.schema_version === "priority-adapter-v0.1", "priority wrapper must preserve adapter schema");
    assert(snapshot.service_area === "BKN", "priority wrapper must preserve requested area scope");

    const pknResponse = await fetch(`http://127.0.0.1:${port}/api/priority-adapter/snapshot?area=PKN`, { headers });
    assert(pknResponse.status === 503, "unconfigured PKN source must fail closed");
  });

  await runServer(3122, {
    SHADOW_CANDIDATE_ENDPOINTS_ENABLED: "true",
    SHADOW_CANDIDATE_ENDPOINT_API_KEY: "candidate-test-key",
    INCIDENT_EVIDENCE_PROJECTION_SOURCE_URL: `http://127.0.0.1:${upstreamPort}/incident-sensitive`,
    INCIDENT_EVIDENCE_PROJECTION_SOURCE_API_KEY: "upstream-test-key",
    PRIORITY_SNAPSHOT_BKN_SOURCE_URL: `http://127.0.0.1:${upstreamPort}/priority-mismatch`,
    PRIORITY_SNAPSHOT_BKN_SOURCE_API_KEY: "upstream-test-key"
  }, async (port) => {
    const headers = { "X-API-Key": "candidate-test-key" };
    const evidenceResponse = await fetch(`http://127.0.0.1:${port}/api/incidents/evidence-projection`, { headers });
    assert(evidenceResponse.status === 502, "sensitive incident source must be rejected");

    const priorityResponse = await fetch(`http://127.0.0.1:${port}/api/priority-adapter/snapshot?area=BKN`, { headers });
    assert(priorityResponse.status === 502, "area-mismatched priority source must be rejected");
  });

  await runServer(3124, {
    SHADOW_CANDIDATE_ENDPOINTS_ENABLED: "true",
    SHADOW_CANDIDATE_ENDPOINT_API_KEY: "candidate-test-key",
    N8N_PRIORITY_READ_BASE_URL: `http://127.0.0.1:${upstreamPort}`,
    N8N_PRIORITY_READ_API_KEY: "n8n-read-test-key",
    N8N_PRIORITY_WORKFLOW_ID: "PEAPriorityAdapterV01",
    PRIORITY_SNAPSHOT_MAX_AGE_MS: "900000"
  }, async (port) => {
    const headers = { "X-API-Key": "candidate-test-key" };
    const bkn = await fetch(`http://127.0.0.1:${port}/api/priority-adapter/snapshot?area=BKN`, { headers });
    const bknBody = await bkn.json();
    assert(bkn.status === 200 && bknBody.service_area === "BKN", "fresh BKN n8n execution-history snapshot must be accepted read-only");

    const pkn = await fetch(`http://127.0.0.1:${port}/api/priority-adapter/snapshot?area=PKN`, { headers });
    const pknBody = await pkn.json();
    assert(pkn.status === 503 && pknBody.error_code === "PRIORITY_PKN_SNAPSHOT_STALE", "stale PKN execution must not be surfaced as live priority");
  });
} finally {
  upstream.close();
}

console.log("SHADOW_SOURCE_CANDIDATES_SMOKE_PASS");
console.log(JSON.stringify({ cases: 10, projection: "pea-incident-evidence.v1", priority_scope: "area-specific", n8n_execution_history: "read-only + freshness-gated", default_state: "disabled", production_send: "blocked" }));
