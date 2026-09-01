# Shadow Source Candidates Acceptance — 2026-09-01

Status: PASS — READ-ONLY SOURCE CANDIDATES READY / REAL UPSTREAM CONNECTIONS NOT YET ACTIVATED

## Candidate A — Aggregate Incident Evidence Projection

Endpoint candidate:

`GET /api/incidents/evidence-projection`

Input source contract:

`pea-incident-aggregate-source.v0.1`

Output contract:

`pea-incident-evidence.v1`

Semantics:

- read-only server-side pull only;
- `mode=shadow`;
- `production_send=blocked`;
- `authoritative_outage_truth=false`;
- no customer name, phone, email, meter/PEANO, raw message/text or coordinates may pass the projection boundary;
- malformed or privacy-unsafe aggregate input fails the whole projection closed rather than partially publishing it;
- the projection does not infer outage truth, transformer identity, feeder identity, affected-customer count, critical-customer state or priority.

Required server configuration:

- `SHADOW_CANDIDATE_ENDPOINTS_ENABLED=true`
- `SHADOW_CANDIDATE_ENDPOINT_API_KEY=<dedicated candidate read key>`
- `INCIDENT_EVIDENCE_PROJECTION_SOURCE_URL=<approved read-only aggregate incident source>`
- optional `INCIDENT_EVIDENCE_PROJECTION_SOURCE_API_KEY`

The candidate endpoints are disabled by default. Enabling them without a dedicated endpoint key still fails closed.

## Candidate B — Area-Scoped Priority Adapter Snapshot Wrapper

Endpoint candidate:

`GET /api/priority-adapter/snapshot?area=BKN`

or

`GET /api/priority-adapter/snapshot?area=PKN`

Output contract remains:

`priority-adapter-v0.1`

Semantics:

- read-only server-side pull only;
- upstream `mode=shadow`, `production_send=blocked`, `purpose=decision_support_only`, `authoritative_outage_truth=false` are mandatory;
- `service_area` must exactly match the requested area;
- missing/mismatched area fails closed;
- score range, score thresholds, priority bands and outage truth are not inferred by the wrapper;
- `queue_rank` remains area-scoped. BKN rank and PKN rank must not be interpreted as one global cross-area rank unless a future explicit cross-area scoring contract defines that semantic.

Area-specific source configuration:

- `PRIORITY_SNAPSHOT_BKN_SOURCE_URL`
- `PRIORITY_SNAPSHOT_PKN_SOURCE_URL`
- optional area-specific source API keys, or shared `PRIORITY_SNAPSHOT_SOURCE_API_KEY`

This design prevents an evolving BKN flow from becoming the implicit contract for PKN.

## Existing Runtime Facts Preserved

The currently inspected `PEAPriorityAdapterV01` candidate remains an inactive n8n subworkflow invoked through `executeWorkflowTrigger`; it does not currently provide an approved read-only GET snapshot endpoint.

The existing Incident Correlation read contract is per ticket (`GET /api/v1/chatbot-reports/{ticket_id}/correlation`), not an operator-wide aggregate incident list. Therefore no real aggregate source URL was fabricated for this milestone.

## Verification

- Next.js production build: PASS.
- `smoke:shadow-source-candidates`: 7 assertions/cases PASS.
  - candidates disabled by default;
  - candidate endpoint auth fails closed when configured;
  - safe aggregate incident source projects to `pea-incident-evidence.v1`;
  - privacy-unsafe incident source is rejected;
  - BKN priority snapshot is accepted only with matching `service_area=BKN`;
  - unconfigured PKN snapshot fails closed;
  - area-mismatched priority snapshot is rejected.
- `smoke:shadow-publisher`: 5/5 PASS regression.
- `smoke:incident-feed`: 4/4 PASS regression.
- `smoke:incident-compose`: 6/6 PASS regression.
- `smoke:priority-adapter`: 5/5 PASS regression.

All source-candidate tests use synthetic local fixtures. They prove contract/transport/privacy behavior only and are not operational evidence.

## Non-Impact Boundary

No n8n workflow was activated or modified. No organization-server runtime, API 18090, GIS, topology, firewall, customer notification or production-send setting was changed.

## Remaining Real-Data Gate

Before the operator page can claim `LIVE_SHADOW`, two real read-only sources still need to exist:

1. an approved aggregate incident source that can emit the fields required by `pea-incident-aggregate-source.v0.1` without exposing customer-sensitive data;
2. approved area-scoped read-only priority snapshot sources for BKN/PKN, or an equivalent wrapper around `PEAPriorityAdapterV01` that does not activate customer-facing behavior.

After those are available, configure the candidate endpoints, run real shadow contract checks, then point the shadow publisher to them and perform end-to-end verification before configuring `INCIDENT_QUEUE_FEED_URL` as live.
