const baseUrl = process.env.PRIORITY_ADAPTER_SMOKE_BASE_URL || "http://127.0.0.1:3101";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function post(payload) {
  const response = await fetch(`${baseUrl}/api/priority-adapter/normalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return { status: response.status, body: await response.json() };
}

const base = {
  mode: "shadow",
  production_send: "blocked",
  purpose: "decision_support_only",
  authoritative_outage_truth: false,
  schema_version: "priority-adapter-v0.1"
};

const bkn = await post({
  ...base,
  adapter_status: "ok",
  ticket_id: "TEST-BKN-001",
  service_area: "BKN",
  queue_count: 2,
  queues: [
    {
      queue_rank: 2,
      transformer_id: "12-345678",
      feeder_code: "BUB07",
      event_type: "Transformer Outage",
      priority_score: 40,
      ai_summary: "synthetic contract test"
    },
    {
      queue_rank: 1,
      transformer_id: "63-006344",
      feeder_code: "BUA03",
      event_type: "Area Outage",
      priority_score: "4/5",
      ai_summary: "synthetic opaque score representation"
    }
  ]
});
assert(bkn.status === 200, "BKN fixture should return 200");
assert(bkn.body.adapter_status === "ok", "BKN adapter status should be ok");
assert(bkn.body.service_area === "BKN", "BKN service_area must be preserved");
assert(bkn.body.queues[0].queue_rank === 1, "queue_rank must drive normalized order");
assert(bkn.body.queues[0].priority_score === "4/5", "opaque score representation must be preserved");
assert(bkn.body.queues[1].priority_score === 40, "numeric score must be preserved without rescaling");
assert(bkn.body.queues[1].priority_level === "", "missing priority_level must stay unspecified");

const pkn = await post({
  ...base,
  adapter_status: "ok",
  ticket_id: "TEST-PKN-001",
  service_area: "PKN",
  queue_count: 1,
  queues: [
    {
      queue_rank: 1,
      transformer_id: "PKN-TX-SYNTHETIC",
      feeder_code: "PKN-SYNTHETIC",
      event_type: "Synthetic Event",
      priority_score: 7.5,
      raw_priority_score: 75,
      score_max: 10,
      priority_level: "HIGH",
      ai_summary: "synthetic contract test"
    }
  ]
});
assert(pkn.status === 200, "PKN fixture should return 200");
assert(pkn.body.service_area === "PKN", "PKN service_area must be preserved");
assert(pkn.body.queues[0].score_max === 10, "score_max must be preserved when supplied");
assert(pkn.body.queues[0].priority_level === "HIGH", "upstream priority_level must be preserved");

const unavailable = await post({
  ...base,
  adapter_status: "unavailable",
  ticket_id: "TEST-UNAVAILABLE",
  service_area: "BKN",
  queue_count: 0,
  queues: [],
  error_code: "PRIORITY_SERVICE_UNAVAILABLE"
});
assert(unavailable.status === 200, "unavailable fixture should remain a valid contract response");
assert(unavailable.body.queue_count === 0, "unavailable response must not fabricate queue items");
assert(unavailable.body.error_code === "PRIORITY_SERVICE_UNAVAILABLE", "unavailable error code must be preserved");

const insufficient = await post({
  ...base,
  adapter_status: "input_insufficient",
  ticket_id: "TEST-INPUT",
  service_area: "PKN",
  queue_count: 0,
  queues: [],
  error_code: "PRIORITY_INPUT_INSUFFICIENT"
});
assert(insufficient.status === 200, "input-insufficient fixture should remain a valid contract response");
assert(insufficient.body.queue_count === 0, "input-insufficient response must not fabricate queue items");

const unsafe = await post({
  ...base,
  production_send: "enabled",
  adapter_status: "ok",
  ticket_id: "TEST-UNSAFE",
  service_area: "BKN",
  queues: []
});
assert(unsafe.status === 422, "unsafe guardrail mutation must be rejected");
assert(unsafe.body.adapter_status === "contract_invalid", "unsafe guardrail mutation must fail closed");
assert(unsafe.body.contract_errors.includes("PRODUCTION_SEND_NOT_BLOCKED"), "guardrail violation must be explicit");

console.log("PRIORITY_ADAPTER_CONTRACT_SMOKE_PASS");
console.log(JSON.stringify({ cases: 5, baseUrl, guardrails: "shadow/blocked/non-authoritative" }));
