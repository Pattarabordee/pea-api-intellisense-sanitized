# Real Shadow Read Projections — Acceptance — 2026-09-01

Status: `PASS_CODE_AND_CONTRACT / NOT_DEPLOYED_AS_LIVE_SHADOW`

## Scope

This acceptance closes the code/contract gate for real read-only Incident Priority Queue sources on the current sanitized PEA Intellisense baseline. It does not deploy or activate a runtime.

Integration worktree:
- `D:\PEA-Intellisense-priority-queue-current`
- branch `feat/incident-priority-queue-current-20260901`
- current code commit after CI fix: `de9a91b`
- current baseline lineage includes sanitized revision `67e45f4` with durable Incident Correlation support.

The prior priority-queue UI commits were reconciled onto the current baseline instead of extending the older `origin/main=fafb96d` lineage.

## Read projection 1 — durable Incident Correlation aggregate

New Go API route:

`GET /api/v1/incidents/correlation-aggregate`

Contract:

`pea-incident-aggregate-source.v0.1`

Properties:
- authenticated with the existing integration authorization boundary;
- available only while Incident Correlation is configured in `shadow` mode;
- reads backend-owned durable correlation reports, latest memberships and latest cluster revisions;
- emits only active correlated clusters;
- raw internal cluster IDs and ticket IDs are not emitted; incident identity is a hashed reference;
- service area is resolved strictly to BKN or PKN; unknown/ambiguous area is omitted instead of guessed;
- transformer/feeder evidence is nullable when not unique;
- `affected_customers=null` because Incident Correlation v1 has no authoritative affected-customer count;
- `report_count` is kept separate and is never treated as customer impact;
- `critical_customer_risk=NOT_EVALUATED` because that evidence is not present in this source;
- no numeric correlation confidence score is exposed;
- `operational_incident_confirmed=false`, `root_cause_confirmed=false`, `authoritative_outage_truth=false`;
- projected incident status is `NEW`, not an invented operator acknowledgement/dispatch state.

## Read projection 2 — n8n priority execution-history snapshot

The web priority snapshot wrapper can read the n8n Public API execution history for `PEAPriorityAdapterV01` without triggering or activating the workflow.

Guardrails:
- `GET` only;
- n8n API-key authentication remains server-side;
- successful execution history only;
- extracts only known final adapter nodes (`Normalize Priority Result`, `Priority Unavailable`, `Priority Input Insufficient`);
- validates the existing `priority-adapter-v0.1` contract;
- requires exact `service_area` match;
- freshness-gated; stale executions are not treated as live priority;
- no score rescaling, threshold invention or global BKN-vs-PKN ranking semantics;
- no browser-to-n8n dependency.

## UI reconciliation

The current PEA Intellisense Mission Control remains at `/`.

Incident Priority Queue is an additive feature at:

`/incident-priority`

Real-evidence-safe UI semantics now support:
- nullable transformer/feeder;
- nullable affected-customer count;
- separate `report_count`;
- area-scoped ranking (`BKN #n`, `PKN #n`), not a fabricated global rank.

## Verification

Local verification:
- `npm ci` — PASS, 0 vulnerabilities;
- production Next.js build — PASS;
- shadow source candidate smoke — 10/10 PASS;
- shadow publisher smoke — 5/5 PASS;
- incident feed smoke — 4/4 PASS;
- incident compose smoke — 6/6 PASS;
- priority adapter smoke — 5/5 PASS;
- Git diff checks — PASS.

CI history:
- first manual `Production Cloud CI` run `33517056948` correctly failed the Go build due to two missing loop braces in the new topology projection;
- defect fixed in commit `de9a91b`;
- second manual `Production Cloud CI` run `33517317138` — PASS:
  - Go API tests — PASS;
  - Python guardrails and sanitized export — PASS;
  - Next.js console install/audit/build — PASS.

The GitHub Actions Node.js 20 deprecation messages are upstream action-runner warnings and did not fail any job.

## Safety / non-actions

This slice did NOT:
- deploy or promote the new Go route to an operational runtime;
- activate a customer-facing n8n workflow;
- trigger `PEAPriorityAdapterV01` to manufacture a fresh snapshot;
- enable `production_send`;
- send customer messages;
- dispatch crews;
- modify GIS/topology services, firewall or public ingress;
- treat correlation/topology/priority evidence as authoritative outage truth.

## Remaining gate

The implementation is code-proven but is not yet `LIVE_SHADOW`.

A separate runtime-integration gate is required to:
1. deploy these read-only candidates to an isolated/current candidate runtime;
2. configure the aggregate source and n8n read-only credentials without exposing them to the browser;
3. verify real durable Incident Correlation rows and fresh real priority execution history exist;
4. run end-to-end `incident-queue-feed.v1` acceptance with explicit source health;
5. keep fallback visible and fail closed if either source is missing/stale/invalid.

Runtime promotion/activation remains a separate consequential decision.
