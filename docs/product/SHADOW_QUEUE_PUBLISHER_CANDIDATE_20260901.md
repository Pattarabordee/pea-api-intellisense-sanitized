# Shadow Incident Queue Publisher Candidate — 2026-09-01

Status: PASS — CANDIDATE IMPLEMENTED / REAL UPSTREAM ACTIVATION NOT YET AUTHORIZED

## Purpose

Provide a server-side, read-only publisher that composes privacy-safe PEA incident evidence with the verified `priority-adapter-v0.1` decision-support contract and emits the stable `incident-queue-feed.v1` contract consumed by the operator web app.

No browser-to-n8n path is introduced.

## Implemented

Endpoint:

`GET /api/incidents/publish-shadow`

Server-only source configuration:

- `SHADOW_QUEUE_INCIDENT_SOURCE_URL`
- optional `SHADOW_QUEUE_INCIDENT_SOURCE_API_KEY`
- `SHADOW_QUEUE_PRIORITY_SOURCE_URL`
- optional `SHADOW_QUEUE_PRIORITY_SOURCE_API_KEY`
- optional `SHADOW_QUEUE_PUBLISH_TIMEOUT_MS`

Consumer wiring remains separate:

- `INCIDENT_QUEUE_FEED_URL`
- optional `INCIDENT_QUEUE_FEED_API_KEY`

A deployment may later point `INCIDENT_QUEUE_FEED_URL` at the approved publisher endpoint. This is not enabled in any shared runtime by this change.

## Incident evidence source contract

Schema: `pea-incident-evidence.v1`

Required outer guardrails:

- `mode=shadow`
- `production_send=blocked`
- `authoritative_outage_truth=false`
- bounded item count
- unique `incident_id`

Accepted incident fields are limited to the operator decision-support view model: incident/area identifiers, transformer/feeder context, affected scope, critical-load risk summary, evidence strength, timestamps, workflow status, event type, safe summary/reasons, and evidence-chain labels.

The source validator rejects obvious sensitive/raw fields such as customer name/phone/email, meter number/PEANO, raw message text, chat input, and coordinates. Free-text operator fields also fail closed on email-like or long contiguous numeric identifiers.

## Priority source behavior

The priority source must return the already verified `priority-adapter-v0.1` contract.

The publisher does not invent or normalize score ranges. It preserves upstream `queue_rank`, score metadata, and priority level only when the priority contract is valid.

If the priority source is unavailable or contract-invalid while the incident evidence source remains healthy:

- real shadow incidents are still published;
- priority fields become `UNRATED` / `null`;
- `priority_state=UNAVAILABLE` (or equivalent composed fallback state);
- no synthetic priority is fabricated;
- the feed remains live rather than replacing real incidents with demo data.

If the incident evidence source is unavailable or invalid, publication is blocked because incident membership/identity must not be fabricated.

## Publisher health metadata

`incident-queue-feed.v1` now optionally carries:

```text
upstream_health.incident_source
upstream_health.priority_source
```

Allowed states:

- `OK`
- `UNAVAILABLE`
- `CONTRACT_INVALID`
- `NOT_CONFIGURED`

The web feed loader keeps `LIVE_SHADOW` when incident evidence is healthy but the priority source is degraded, and states explicitly that incidents are being shown as UNRATED.

## Verification

- Next.js production build: PASS.
- `smoke:shadow-publisher`: 5/5 PASS.
  - healthy incident + healthy priority -> valid `incident-queue-feed.v1`, multi-area queue preserved, page consumes publisher through feed layer;
  - healthy incident + priority HTTP failure -> real incidents remain live, scores/levels are not fabricated;
  - healthy incident + unsafe priority contract -> priority rejected, incidents remain UNRATED;
  - incident payload containing forbidden customer phone field -> publisher blocks with `INCIDENT_SOURCE_CONTRACT_INVALID`;
  - incident source not configured -> publisher blocks with `INCIDENT_SOURCE_NOT_CONFIGURED`.

All acceptance sources used by this smoke are synthetic and prove only software/contract behavior.

## Important real-source finding

Two upstream gaps remain before this can be called a real live-shadow feed:

1. `PEAPriorityAdapterV01` is currently an inactive n8n subworkflow (`executeWorkflowTrigger` + manual test trigger). It does not expose a read-only GET snapshot endpoint. Therefore the publisher must not pretend it can call that workflow directly by URL. A separately approved wrapper/snapshot source must expose its normalized `priority-adapter-v0.1` result.

2. The current Incident Correlation read contract is ticket-scoped (`GET /api/v1/chatbot-reports/{ticket_id}/correlation`). It deliberately exposes a safe correlation summary but is not an aggregate incident-list endpoint and does not by itself satisfy `pea-incident-evidence.v1`. A backend-owned aggregate read projection or approved snapshot export is still required.

These are source-availability gaps, not frontend/publisher contract gaps.

## Non-impact verification

This slice did not:

- activate or modify `PEAPriorityAdapterV01`;
- modify the teammate priority calculator;
- create/activate an n8n webhook;
- mutate organization-server runtime;
- change API 18090, GIS/resolver/topology services, firewall, customer send, or production-send state;
- expose credentials to the browser.

## Next gate

Build the two read-only source projections without changing customer behavior:

1. backend-owned aggregate `pea-incident-evidence.v1` projection from durable incident/correlation evidence;
2. read-only `priority-adapter-v0.1` snapshot wrapper around the inactive/candidate priority lane;
3. test both independently with real shadow data;
4. point the publisher candidate at those two sources;
5. only after real-source acceptance set `INCIDENT_QUEUE_FEED_URL` for the operator app.
