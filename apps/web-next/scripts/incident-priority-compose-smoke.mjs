const baseUrl = process.env.PRIORITY_COMPOSE_BASE_URL || "http://127.0.0.1:3102";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function post(payload) {
  const response = await fetch(`${baseUrl}/api/incidents/compose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const body = await response.json();
  assert(response.ok, `HTTP_${response.status}_${JSON.stringify(body)}`);
  return body;
}

function incident(overrides = {}) {
  return {
    incident_id: "INC-BKN-001",
    area: "BKN",
    area_label: "บึงกาฬ",
    transformer_id: "63-006344",
    feeder_id: "BUA03",
    affected_customers: 135,
    critical_customer_risk: "critical-load-review",
    evidence_strength: "STRONG",
    first_reported_at: "2026-09-01T14:00:00+07:00",
    waiting_minutes: 30,
    status: "NEW",
    event_type: "SUSPECTED_OUTAGE",
    ai_summary: "PEA evidence summary",
    priority_reasons: ["PEA impact evidence"],
    evidence_chain: ["Incident correlation", "Topology evidence"],
    ...overrides
  };
}

function priority(overrides = {}) {
  return {
    mode: "shadow",
    production_send: "blocked",
    purpose: "decision_support_only",
    authoritative_outage_truth: false,
    schema_version: "priority-adapter-v0.1",
    adapter_status: "ok",
    ticket_id: "TICKET-001",
    service_area: "BKN",
    queue_count: 1,
    queues: [
      {
        queue_rank: 1,
        transformer_id: "63-006344",
        feeder_code: "BUA03",
        event_type: "Transformer Outage",
        event_status: "suspected",
        priority_score: "40",
        raw_priority_score: "40",
        score_max: null,
        priority_level: "HIGH",
        ai_summary: "Priority calculator explanation",
        source: "synthetic-contract-fixture"
      }
    ],
    ...overrides
  };
}

const bkn = await post({ priority: priority(), incidents: [incident()], generated_at: "2026-09-01T15:00:00+07:00" });
assert(bkn.mode === "shadow" && bkn.production_send === "blocked", "BKN_GUARDRAIL_FAIL");
assert(bkn.authoritative_outage_truth === false, "BKN_AUTHORITY_FAIL");
assert(bkn.matched_signal_count === 1, "BKN_MATCH_FAIL");
assert(bkn.snapshot.items[0].priority_score === 40, "BKN_SCORE_PARSE_FAIL");
assert(bkn.snapshot.items[0].priority_level === "HIGH", "BKN_LEVEL_FAIL");
assert(bkn.snapshot.items[0].queue_rank === 1, "BKN_RANK_FAIL");
assert(bkn.snapshot.items[0].source_mode === "PRIORITY_ADAPTER", "BKN_SOURCE_FAIL");

const pkn = await post({
  priority: priority({
    service_area: "PKN",
    queues: [{
      queue_rank: 2,
      transformer_id: "PKN-TX-014",
      feeder_code: "PKN02",
      event_type: "Area Outage",
      event_status: "review",
      priority_score: null,
      raw_priority_score: "opaque-v2",
      score_max: null,
      priority_level: "MEDIUM",
      ai_summary: "PKN adapter explanation",
      source: null
    }]
  }),
  incidents: [incident({ incident_id: "INC-PKN-001", area: "PKN", area_label: "พังโคน", transformer_id: "PKN-TX-014", feeder_id: "PKN02" })]
});
assert(pkn.matched_signal_count === 1, "PKN_MATCH_FAIL");
assert(pkn.snapshot.items[0].priority_score === null, "PKN_SCORE_SHOULD_REMAIN_NULL");
assert(pkn.snapshot.items[0].priority_level === "MEDIUM", "PKN_LEVEL_FAIL");
assert(pkn.snapshot.items[0].queue_rank === 2, "PKN_RANK_FAIL");

const unavailable = await post({
  priority: priority({ adapter_status: "unavailable", queue_count: 0, queues: [], error_code: "PRIORITY_SERVICE_UNAVAILABLE" }),
  incidents: [incident()]
});
assert(unavailable.snapshot.items.length === 1, "UNAVAILABLE_INCIDENT_DROPPED");
assert(unavailable.snapshot.items[0].priority_score === null, "UNAVAILABLE_SCORE_FABRICATED");
assert(unavailable.snapshot.items[0].priority_level === "UNRATED", "UNAVAILABLE_LEVEL_NOT_UNRATED");
assert(unavailable.snapshot.items[0].priority_state === "UNAVAILABLE", "UNAVAILABLE_STATE_FAIL");

const unsafe = await post({
  priority: priority({ production_send: "enabled" }),
  incidents: [incident()]
});
assert(unsafe.adapter_status === "contract_invalid", "UNSAFE_NOT_REJECTED");
assert(unsafe.snapshot.items[0].priority_state === "CONTRACT_INVALID", "UNSAFE_STATE_FAIL");
assert(unsafe.snapshot.items[0].priority_score === null, "UNSAFE_SCORE_FABRICATED");

const ambiguous = await post({
  priority: priority(),
  incidents: [incident({ incident_id: "INC-BKN-A" }), incident({ incident_id: "INC-BKN-B" })]
});
assert(ambiguous.matched_signal_count === 0, "AMBIGUOUS_SHOULD_NOT_MATCH");
assert(ambiguous.unmatched_signal_count === 1, "AMBIGUOUS_SIGNAL_COUNT_FAIL");
assert(ambiguous.snapshot.items.every((item) => item.priority_state === "UNMATCHED" && item.priority_score === null), "AMBIGUOUS_FAIL_CLOSED_FAIL");
assert(ambiguous.warnings.includes("QUEUE_1_AMBIGUOUS_INCIDENT_MATCH"), "AMBIGUOUS_WARNING_MISSING");

const areaMismatch = await post({
  priority: priority({ service_area: "PKN" }),
  incidents: [incident()]
});
assert(areaMismatch.matched_signal_count === 0, "AREA_MISMATCH_SHOULD_NOT_MATCH");
assert(areaMismatch.snapshot.items[0].priority_state === "UNMATCHED", "AREA_MISMATCH_STATE_FAIL");

console.log("INCIDENT_PRIORITY_COMPOSE_SMOKE_PASS");
console.log(JSON.stringify({ cases: 6, baseUrl, guardrails: "shadow/blocked/non-authoritative", matching: "exact unique transformer + area" }));
