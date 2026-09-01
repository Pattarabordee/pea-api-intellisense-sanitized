# Incident Priority Queue — UI Contract v1

Status: SHADOW / MOCK-FIRST UI / VERIFIED PRIORITY-ADAPTER CONSUMER BOUNDARY

## Purpose

Define a stable frontend boundary for the PEA Intellisense Incident Priority Queue while the teammate's Bueng Kan / Phang Khon priority calculator continues evolving.

The frontend MUST NOT depend on a specific n8n workflow ID, BKN-only request shape, score range, threshold, or raw message structure.

## Verified upstream boundary

The organization-server n8n lane already has a tested candidate adapter:

- workflow: `PEAPriorityAdapterV01`
- schema: `priority-adapter-v0.1`
- status at this checkpoint: inactive/unpublished candidate after synthetic verification
- guardrails: `mode=shadow`, `production_send=blocked`, `purpose=decision_support_only`, `authoritative_outage_truth=false`
- output: `ticket_id`, `service_area`, `adapter_status`, `queue_count`, `queues[]`
- queue item fields: `queue_rank`, `transformer_id`, `feeder_code`, `event_type`, `event_status`, `priority_score`, optional `raw_priority_score`, optional `score_max`, optional `priority_level`, `ai_summary`, optional `source`

The upstream calculator is still evolving. The web lane therefore MUST NOT infer priority bands or normalize a score unless the adapter explicitly supplies stable score semantics. Live ordering should respect `queue_rank`, not hard-code numeric score thresholds.

## Web normalization boundary

`PEAPriorityAdapterV01 -> /api/priority-adapter/normalize -> normalized priority signal -> incident evidence/view-model join -> Operator Queue`

Implemented web normalization:

- `apps/web-next/lib/priority-adapter.ts`
- `apps/web-next/app/api/priority-adapter/normalize/route.ts`
- `apps/web-next/scripts/priority-adapter-contract-smoke.mjs`

The normalizer:

- rejects any response that weakens shadow/blocked/non-authoritative guardrails;
- preserves `service_area` for multi-area readiness;
- preserves numeric or string score representations without rescaling;
- preserves optional `score_max` and `priority_level` only when upstream provides them;
- sorts normalized signal items by `queue_rank`;
- returns no fabricated queue items for `unavailable` or `input_insufficient` states;
- does not infer outage truth, transformer truth, feeder truth, dispatch action, or customer impact.

## Canonical incident UI item

The current mock-first `incident-priority.v1` view model contains:

- `incident_id`
- `area`, `area_label`
- `priority_score`, `priority_level`
- `event_type`
- `transformer_id`, `feeder_id`
- `affected_customers`
- `critical_customer_risk`
- `evidence_strength`
- `first_reported_at`, `waiting_minutes`
- `status`
- `ai_summary`
- `priority_reasons[]`
- `evidence_chain[]`
- `source_mode`

The fields beyond the n8n priority signal (for example affected scope, evidence strength, incident lifecycle and evidence chain) must come from PEA Intellisense incident/evidence context. They must not be fabricated by the priority adapter.

## Safety

- Queue incidents, not raw messages.
- Priority is decision-support, not authoritative outage truth.
- No customer/crew dispatch write is enabled in v1.
- Operator Review remains non-actioning in the mock-first slice.
- Keep `mode=shadow` and `production_send=blocked`.
- Synthetic data must be visibly labeled and must not be presented as measured operational evidence.
- Do not hard-code BKN/PKN score thresholds while upstream semantics remain unstable.

## Current UI implementation

- Frontend: `apps/web-next/app/incident-priority-queue.tsx`
- Contract/demo fixture: `apps/web-next/lib/incident-priority.ts`
- Route: `/`
- Filters: area and priority level
- Mock ordering: synthetic active incidents before restored, then synthetic score order for demonstration only
- Detail view: rationale + evidence chain + explicit operator gate

## Next integration gate

Build a small incident-priority view-model join that combines the normalized `priority-adapter-v0.1` signal with existing PEA Intellisense incident/evidence context. Acceptance must cover at least:

1. BKN adapter success;
2. PKN adapter success;
3. `unavailable` and timeout/failure semantics;
4. `input_insufficient`;
5. missing `priority_level` / missing `score_max` without local threshold invention;
6. malformed or unsafe guardrail response rejected fail-closed;
7. incident context unavailable without fabricated affected-customer/evidence fields;
8. restored/closed incident handling without silently overriding upstream queue semantics.

Do not connect the browser directly to the teammate calculator workflow.


## Compose boundary — 2026-09-01

The verified web-side join is now:

`PEAPriorityAdapterV01 -> web normalizer -> /api/incidents/compose + PEA incident evidence -> incident-priority.v1 -> Operator Queue`

Matching is fail-closed: exact unique `transformer_id` plus compatible `service_area`. No queue item is assigned by array position, fuzzy text, score similarity, or guessed area mapping. Priority score/level remains decision-support metadata; missing score/level is represented as `null` / `UNRATED` rather than fabricated.

The browser route still uses labeled synthetic demo data until an approved stable read-only queue feed is available. See `INCIDENT_PRIORITY_COMPOSE_ACCEPTANCE_20260901.md`.

## Read-only feed layer — 2026-09-01

The web app now has a stable server-side feed boundary:

`approved shadow publisher -> incident-queue-feed.v1 -> /api/incidents/feed -> operator page`

The browser does not call n8n directly. Upstream URL/API key remain server-only. Source health is explicit (`LIVE_SHADOW`, `NOT_CONFIGURED`, `UPSTREAM_UNAVAILABLE`, `CONTRACT_INVALID`). Invalid or unavailable live data fails closed to visibly labeled synthetic fallback; live and synthetic data are never silently merged.

Real feed activation is still a separate gate because no approved read-only publisher URL is configured yet.

## Shadow publisher candidate — 2026-09-01

A server-side candidate now exists at `GET /api/incidents/publish-shadow`:

`pea-incident-evidence.v1 + priority-adapter-v0.1 -> compose -> incident-queue-feed.v1`

The incident source is mandatory and privacy/fail-closed validated. Priority is decision-support only: if priority transport/contract fails while incident evidence remains valid, real incidents stay visible as `UNRATED` with no fabricated score. The publisher never enables customer send and does not expose source credentials to the browser.

Real-source activation remains blocked on two explicit projections: an aggregate incident-evidence read source and a read-only priority-adapter snapshot wrapper. `PEAPriorityAdapterV01` itself remains inactive and has no GET snapshot trigger.


## Shadow source candidates — 2026-09-01

Two read-only source candidates now sit in front of the publisher boundary:

`aggregate incident source -> /api/incidents/evidence-projection -> pea-incident-evidence.v1`

`area-scoped priority source -> /api/priority-adapter/snapshot?area=BKN|PKN -> priority-adapter-v0.1`

Both candidates are disabled by default and require a dedicated candidate endpoint key when enabled. The incident projection rejects privacy-unsafe input. The priority wrapper requires exact area match and does not infer score scales or bands.

Important ranking semantic: `queue_rank` is preserved as an area-scoped rank. BKN and PKN ranks are not a proven global cross-area ranking contract. Do not compare or re-scale opaque priority scores across areas until the upstream owner defines and verifies a shared cross-area scoring semantic.
