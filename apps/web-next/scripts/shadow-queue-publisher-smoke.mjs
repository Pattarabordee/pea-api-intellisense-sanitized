import http from "node:http";
import { spawn } from "node:child_process";

const upstreamPort = 3196;
const now = "2026-09-01T16:05:00+07:00";

const incidentEnvelope = {
  schema_version: "pea-incident-evidence.v1",
  mode: "shadow",
  production_send: "blocked",
  authoritative_outage_truth: false,
  generated_at: now,
  source_id: "synthetic-incident-source",
  items: [
    {
      incident_id: "INC-BKN-PUBLISH-001",
      area: "BKN",
      area_label: "บึงกาฬ",
      transformer_id: "SYNTH-BKN-TX-01",
      feeder_id: "SYNTH-BKN-FDR-01",
      affected_customers: 25,
      critical_customer_risk: "synthetic critical-load flag",
      evidence_strength: "STRONG",
      first_reported_at: now,
      waiting_minutes: 11,
      status: "NEW",
      event_type: "SYNTHETIC_OUTAGE",
      ai_summary: "Synthetic incident evidence for publisher contract testing.",
      priority_reasons: ["synthetic incident evidence"],
      evidence_chain: ["synthetic report correlation", "synthetic topology evidence"]
    },
    {
      incident_id: "INC-PKN-PUBLISH-002",
      area: "PKN",
      area_label: "พังโคน",
      transformer_id: "SYNTH-PKN-TX-02",
      feeder_id: "SYNTH-PKN-FDR-02",
      affected_customers: 9,
      critical_customer_risk: "synthetic no-critical-load flag",
      evidence_strength: "MODERATE",
      first_reported_at: now,
      waiting_minutes: 7,
      status: "ACKNOWLEDGED",
      event_type: "SYNTHETIC_OUTAGE",
      ai_summary: "Synthetic incident evidence for multi-area contract testing.",
      priority_reasons: ["synthetic multi-area evidence"],
      evidence_chain: ["synthetic report correlation", "synthetic transformer evidence"]
    }
  ]
};

const priorityEnvelope = {
  mode: "shadow",
  production_send: "blocked",
  purpose: "decision_support_only",
  authoritative_outage_truth: false,
  schema_version: "priority-adapter-v0.1",
  adapter_status: "ok",
  ticket_id: "SYNTHETIC-SNAPSHOT",
  service_area: "",
  queue_count: 2,
  queues: [
    {
      queue_rank: 2,
      transformer_id: "SYNTH-BKN-TX-01",
      feeder_code: "SYNTH-BKN-FDR-01",
      event_type: "Synthetic Event",
      event_status: "active",
      priority_score: 40,
      raw_priority_score: null,
      score_max: null,
      priority_level: "HIGH",
      ai_summary: "Synthetic BKN priority decision-support signal.",
      source: "synthetic"
    },
    {
      queue_rank: 1,
      transformer_id: "SYNTH-PKN-TX-02",
      feeder_code: "SYNTH-PKN-FDR-02",
      event_type: "Synthetic Event",
      event_status: "active",
      priority_score: 7.5,
      raw_priority_score: 75,
      score_max: 10,
      priority_level: "CRITICAL",
      ai_summary: "Synthetic PKN priority decision-support signal.",
      source: "synthetic"
    }
  ]
};

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) });
  res.end(payload);
}

const upstream = http.createServer((req, res) => {
  if (req.url === "/incidents-ok") {
    if (req.headers["x-api-key"] !== "incident-key") return json(res, 401, { error: "incident key required" });
    return json(res, 200, incidentEnvelope);
  }
  if (req.url === "/incidents-unsafe") {
    if (req.headers["x-api-key"] !== "incident-key") return json(res, 401, { error: "incident key required" });
    const unsafe = structuredClone(incidentEnvelope);
    unsafe.items[0].customer_phone = "0812345678";
    return json(res, 200, unsafe);
  }
  if (req.url === "/incidents-invalid") {
    return json(res, 200, { ...incidentEnvelope, production_send: "enabled" });
  }
  if (req.url === "/priority-ok") {
    if (req.headers["x-api-key"] !== "priority-key") return json(res, 401, { error: "priority key required" });
    return json(res, 200, priorityEnvelope);
  }
  if (req.url === "/priority-invalid") {
    return json(res, 200, { ...priorityEnvelope, production_send: "enabled" });
  }
  if (req.url === "/priority-down") {
    return json(res, 503, { error: "synthetic priority unavailable" });
  }
  return json(res, 404, { error: "not found" });
});

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(url) {
  let lastError;
  for (let i = 0; i < 60; i += 1) {
    try {
      const response = await fetch(url);
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

async function runAppCase({ port, incidentPath, priorityPath, expectedPublishStatus, inspect }) {
  const env = { ...process.env, PORT: String(port), HOSTNAME: "127.0.0.1" };
  delete env.SHADOW_QUEUE_INCIDENT_SOURCE_URL;
  delete env.SHADOW_QUEUE_PRIORITY_SOURCE_URL;
  delete env.SHADOW_QUEUE_INCIDENT_SOURCE_API_KEY;
  delete env.SHADOW_QUEUE_PRIORITY_SOURCE_API_KEY;
  delete env.INCIDENT_QUEUE_FEED_URL;
  if (incidentPath) {
    env.SHADOW_QUEUE_INCIDENT_SOURCE_URL = `http://127.0.0.1:${upstreamPort}${incidentPath}`;
    env.SHADOW_QUEUE_INCIDENT_SOURCE_API_KEY = "incident-key";
  }
  if (priorityPath) {
    env.SHADOW_QUEUE_PRIORITY_SOURCE_URL = `http://127.0.0.1:${upstreamPort}${priorityPath}`;
    env.SHADOW_QUEUE_PRIORITY_SOURCE_API_KEY = "priority-key";
  }
  env.INCIDENT_QUEUE_FEED_URL = `http://127.0.0.1:${port}/api/incidents/publish-shadow`;

  const child = spawn(process.execPath, [".next/standalone/server.js"], {
    cwd: process.cwd(),
    env,
    stdio: ["ignore", "pipe", "pipe"]
  });

  try {
    await waitFor(`http://127.0.0.1:${port}/api/incidents/publish-shadow`);
    const response = await fetch(`http://127.0.0.1:${port}/api/incidents/publish-shadow`);
    const body = await response.json();
    assert(response.status === expectedPublishStatus, `${port}: expected publisher ${expectedPublishStatus}, got ${response.status}`);
    await inspect({ response, body, port });
  } finally {
    await stopChild(child);
  }
}

await new Promise((resolve) => upstream.listen(upstreamPort, "127.0.0.1", resolve));
try {
  await runAppCase({
    port: 3111,
    incidentPath: "/incidents-ok",
    priorityPath: "/priority-ok",
    expectedPublishStatus: 200,
    inspect: async ({ body, port }) => {
      assert(body.schema_version === "incident-queue-feed.v1", "healthy publisher must emit feed contract");
      assert(body.upstream_health.incident_source === "OK", "incident source should be OK");
      assert(body.upstream_health.priority_source === "OK", "priority source should be OK");
      assert(body.snapshot.items.length === 2, "both incidents must be published");
      assert(body.snapshot.items[0].incident_id === "INC-PKN-PUBLISH-002", "queue_rank must order composed feed");
      assert(body.snapshot.items[0].priority_level === "CRITICAL", "upstream priority level must be preserved");
      const page = await (await fetch(`http://127.0.0.1:${port}/`)).text();
      assert(page.includes("INC-PKN-PUBLISH-002"), "operator page must consume publisher feed through read-only feed layer");
      assert(page.includes("LIVE SHADOW"), "operator page must show LIVE SHADOW source state");
    }
  });

  await runAppCase({
    port: 3112,
    incidentPath: "/incidents-ok",
    priorityPath: "/priority-down",
    expectedPublishStatus: 200,
    inspect: async ({ body, port }) => {
      assert(body.upstream_health.priority_source === "UNAVAILABLE", "priority transport failure must be explicit");
      assert(body.snapshot.items.every((item) => item.priority_level === "UNRATED"), "priority failure must not fabricate levels");
      assert(body.snapshot.items.every((item) => item.priority_score === null), "priority failure must not fabricate scores");
      assert(body.snapshot.items.every((item) => item.priority_state === "UNAVAILABLE"), "priority state should degrade to UNAVAILABLE");
      const feed = await (await fetch(`http://127.0.0.1:${port}/api/incidents/feed`)).json();
      assert(feed.source_health.status === "LIVE_SHADOW", "healthy incident source should keep real shadow feed live");
      assert(feed.source_health.fallback_active === false, "priority failure must not replace real incidents with synthetic fallback");
    }
  });

  await runAppCase({
    port: 3113,
    incidentPath: "/incidents-ok",
    priorityPath: "/priority-invalid",
    expectedPublishStatus: 200,
    inspect: async ({ body }) => {
      assert(body.upstream_health.priority_source === "CONTRACT_INVALID", "unsafe priority contract must be rejected");
      assert(body.snapshot.items.every((item) => item.priority_level === "UNRATED"), "invalid priority contract must not influence queue level");
    }
  });

  await runAppCase({
    port: 3114,
    incidentPath: "/incidents-unsafe",
    priorityPath: "/priority-ok",
    expectedPublishStatus: 502,
    inspect: async ({ body, port }) => {
      assert(body.error_code === "INCIDENT_SOURCE_CONTRACT_INVALID", "unsafe incident payload must fail closed");
      assert(body.source_health.incident_source === "CONTRACT_INVALID", "unsafe incident source state must be explicit");
      const feed = await (await fetch(`http://127.0.0.1:${port}/api/incidents/feed`)).json();
      assert(feed.source_health.fallback_active === true, "consumer must fall back visibly when publisher is blocked");
      assert(feed.snapshot.source === "synthetic_demo", "blocked publisher must never leak partial incident data");
    }
  });

  await runAppCase({
    port: 3115,
    incidentPath: null,
    priorityPath: "/priority-ok",
    expectedPublishStatus: 503,
    inspect: async ({ body }) => {
      assert(body.error_code === "INCIDENT_SOURCE_NOT_CONFIGURED", "publisher requires incident evidence source");
      assert(body.source_health.incident_source === "NOT_CONFIGURED", "missing incident source must be explicit");
    }
  });
} finally {
  upstream.close();
}

console.log("SHADOW_QUEUE_PUBLISHER_SMOKE_PASS");
console.log(JSON.stringify({ cases: 5, publisher: "read-only candidate", direct_n8n_browser_access: false, live_incidents_preserved_when_priority_unavailable: true }));
