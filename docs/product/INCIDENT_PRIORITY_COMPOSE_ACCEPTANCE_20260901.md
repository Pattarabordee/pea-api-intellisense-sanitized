# Incident Priority Compose — Acceptance 2026-09-01

Status: PASS — SHADOW VIEW-MODEL COMPOSITION / LIVE FEED NOT YET ENABLED

## Scope

Connect the verified `PEAPriorityAdapterV01` web contract to PEA incident/evidence context without coupling the frontend to a teammate n8n workflow schema and without inventing outage truth, score thresholds, or dispatch actions.

## Implemented

- `apps/web-next/lib/incident-priority-compose.ts`
- `POST /api/incidents/compose`
- `apps/web-next/scripts/incident-priority-compose-smoke.mjs`
- UI support for `UNRATED` priority and null/opaque upstream scores.

The compose boundary accepts:

1. raw `priority-adapter-v0.1` output;
2. PEA incident/evidence records;
3. validates the priority adapter guardrails;
4. joins only on an exact unique `transformer_id` inside a compatible `service_area`;
5. emits `incident-priority.v1` for the Operator Queue.

## Safety / matching policy

- `mode=shadow` required.
- `production_send=blocked` required.
- `authoritative_outage_truth=false` required.
- Priority output never overwrites PEA incident status or creates outage truth.
- No score band is derived downstream.
- Missing/opaque scores remain `null`; they are not converted to zero.
- Missing/unknown priority level becomes `UNRATED`; no band is inferred from score.
- Adapter `queue_rank` is preserved when a signal is matched.
- Exact unique transformer match is required. Multiple active incident candidates on the same transformer fail closed as `UNMATCHED`.
- Service-area mismatch fails closed.
- Adapter unavailable/input-insufficient/contract-invalid states preserve the PEA incident in the UI but mark priority as unavailable/unrated rather than dropping the incident.
- Restored incidents remain behind active incidents.

## Verification

Production build: PASS.

`npm run smoke:incident-compose`:
- 6/6 PASS
- BKN exact match + numeric-string score preservation
- PKN exact match with null score preserved
- priority service unavailable -> incident retained, `UNRATED`, no fabricated score
- unsafe production-send contract -> `CONTRACT_INVALID`, no fabricated score
- duplicate incident candidates on one transformer -> ambiguous match fail-closed
- service-area mismatch -> fail-closed

`npm run smoke:priority-adapter` regression:
- 5/5 PASS after compose changes.

## Current limit / live-data gate

This change completes the web composition boundary but does **not** activate a live production/shadow feed into the browser yet.

Reason: the n8n adapter and integrated shadow candidate are intentionally inactive/unpublished after verification, and there is no approved stable incident-queue snapshot endpoint for the web app to poll. Enabling or publishing a runtime feed is a separate gate.

The current `/` page therefore continues to use visibly labeled synthetic demo data. This is intentional; the UI must not silently present synthetic/captured contract fixtures as live operational incidents.

## Next gate

Create or approve one stable read-only queue-feed boundary that emits either:

- `incident-priority.v1`, or
- PEA incident/evidence + `priority-adapter-v0.1` input to `/api/incidents/compose`.

Then switch the UI source from synthetic fallback to the validated live/shadow snapshot with explicit source-health labeling. Do not activate customer send or crew dispatch as part of that gate.
