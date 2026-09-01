# PEA Intellisense — Priority Adapter Web Consumer Acceptance

Date: 2026-09-01 Asia/Bangkok
Status: PASS — CONTRACT CONSUMER ONLY / NO LIVE BROWSER-TO-N8N CONNECTION

## Scope

Add a web-side fail-closed consumer for the already verified organization-server n8n candidate `PEAPriorityAdapterV01` (`priority-adapter-v0.1`).

This slice does not modify n8n, activate a workflow, call the teammate priority calculator directly, change PEA Intellisense runtime, or enable any customer/crew action.

## Implemented

- `apps/web-next/lib/priority-adapter.ts`
  - validates the n8n adapter guardrails;
  - preserves `service_area`;
  - preserves score values without assuming a range;
  - preserves optional `raw_priority_score`, `score_max`, and `priority_level` only when present;
  - orders normalized signals by upstream `queue_rank`;
  - emits no fabricated queue items when adapter status is unavailable/input-insufficient;
  - fails closed when shadow/blocked/non-authoritative contract fields are weakened.

- `apps/web-next/app/api/priority-adapter/normalize/route.ts`
  - POST normalization boundary for contract acceptance and future server-side integration;
  - returns HTTP 422 for contract/guardrail violations;
  - returns HTTP 400 for invalid JSON;
  - uses `Cache-Control: no-store`.

- `apps/web-next/scripts/priority-adapter-contract-smoke.mjs`
  - BKN success fixture;
  - PKN success fixture;
  - unavailable fixture;
  - input-insufficient fixture;
  - unsafe production-send mutation fixture.

## Important semantic rule

The current upstream priority calculator is evolving. The web consumer does not convert scores into local Critical/High/Medium/Low thresholds and does not rescale a score. A score such as numeric `40` or an opaque representation such as `4/5` is preserved as supplied.

For live integration, queue ordering must follow upstream `queue_rank` until score semantics are formally stabilized. The existing demo dashboard still uses synthetic score bands only for mock presentation and is visibly labeled synthetic.

## Verification

- `npm run build`: PASS; Next.js route `/api/priority-adapter/normalize` compiled successfully.
- standalone Next.js server on local port 3101: READY during test.
- `npm run smoke:priority-adapter`: PASS, 5/5 contract cases.
- guardrail rejection test: PASS for `production_send != blocked` -> HTTP 422 / `contract_invalid`.
- unavailable/input-insufficient: PASS with zero fabricated queue items.
- no n8n workflow/runtime mutation performed in this web-consumer slice.

## Relationship to n8n evidence

Upstream n8n integration evidence remains authoritative for the organization-server adapter contract:

`D:\PEA Intellisense data\handoffs\n8n\20_PRIORITY_ADAPTER_SHADOW_INTEGRATION_EVIDENCE_2026-09-01.md`

That evidence proves orchestration/contract behavior only, not business accuracy or score calibration. This web acceptance inherits the same limitation.

## Next gate

Build the incident-priority view-model join:

`normalized priority signal + PEA incident/evidence context -> incident-priority.v1 -> Operator Queue`

Do not fabricate affected-customer count, evidence strength, incident lifecycle, feeder/transformer truth, or priority level when the authoritative context does not provide them.
