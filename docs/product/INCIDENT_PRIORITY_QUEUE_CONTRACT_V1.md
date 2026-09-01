# Incident Priority Queue — UI Contract v1

Status: SHADOW / MOCK-FIRST / OPERATOR DECISION-SUPPORT

## Purpose

Define a stable frontend boundary for the PEA Intellisense Incident Priority Queue while n8n priority scoring for Bueng Kan and Phang Khon continues independently.

The frontend MUST NOT depend on a specific n8n workflow ID, BKN-only schema, or raw message structure.

## Canonical item

`incident-priority.v1` fields:

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

## Integration boundary

`n8n / scoring source -> Priority Adapter -> incident-priority.v1 -> Operator Queue`

The Priority Adapter is responsible for validation, normalization, area metadata, timeout/error handling, and fail-closed fallback. The UI only consumes the canonical contract.

## Safety

- Queue incidents, not raw messages.
- Priority is decision-support, not authoritative outage truth.
- No customer/crew dispatch write is enabled in v1.
- Operator Review control remains non-actioning in the mock-first slice.
- Keep `mode=shadow` and `production_send=blocked`.
- Synthetic data must be visibly labeled and must not be presented as measured operational evidence.

## Current implementation

- Frontend: `apps/web-next/app/incident-priority-queue.tsx`
- Contract/demo fixture: `apps/web-next/lib/incident-priority.ts`
- Route: `/`
- Filters: area and priority level
- Ordering: active incidents before restored, then descending priority score
- Detail view: rationale + evidence chain + explicit operator gate

## Next integration gate

Do not connect directly to `Priority score outage BKN` or any PKN variant. First implement a canonical Priority Adapter and acceptance fixtures for BKN, PKN, unavailable/timeout, malformed score, missing evidence, and restored incident states.
