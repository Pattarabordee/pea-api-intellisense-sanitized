# PEA API Intellisense Go API

Shadow receiver and meter-state truth ledger for AIS outage/restore observations.

## Guardrails

- `mode = shadow`
- `production_send = blocked`
- No raw meter, PEANO list, room id, token, or customer identity in responses
- AIS outage/restore remains customer-facing truth
- Auto ETR stays blocked until green gate and owner approval pass
- Startup fails when `AIS_INBOUND_API_KEY` or `DATABASE_URL` is missing
- `meter_no` is the meter-state key; `source_event_id` and `site_id` are optional hashed evidence

## Environment

```text
PORT=8090
DATABASE_URL=<Render Postgres internal URL>
AIS_INBOUND_API_KEY=<stored in Render secret/env>
RATE_LIMIT_PER_MINUTE=120
ALLOWED_ORIGIN=<optional Next.js console origin>
```

## Local Run

Requires Go and PostgreSQL:

```powershell
cd apps/api-go
$env:DATABASE_URL="postgres://..."
$env:AIS_INBOUND_API_KEY="<REDACTED_SECRET>"
go test ./...
go run ./cmd/pea-api-intellisense
```

## API

```http
GET  /health
GET  /metrics
GET  /api/v1/ais/truth-intervals?status=OPEN
GET  /api/v1/ais/outage-verifications
POST /api/v1/ais/outage-verifications
GET  /api/v1/ais/outage-verifications/{request_id}
```

Every endpoint except `/health` is operator/integration-only and requires `X-API-Key` or `Authorization: Bearer <key>`. Metrics include aggregate validation, event-semantic source, stale-open, and meter-state counts; no raw identifiers are returned.

`/metrics` returns aggregate counts only: total requests, duplicate callbacks, pending worker traces,
event-semantic mapping counts, meter-state open/closed intervals, stale open intervals, `NOT_READY_FOR_AUTO_SEND`,
and `production_send=blocked`.

Event semantics use strict precedence: explicit `event_type`, exact allowlisted status, then exact
`alarm_type=AC_MAIN_FAIL` as OUTAGE or exact `alarm_type=AC_MAIN_RESTORE` as RESTORE. Cause text never creates truth. The authenticated operator list
returns only sanitized fixed-field `semantic_signals`; unsafe values are hash-reference only.

Prospective alarm mapping uses `semantic_capture_version=v2` and
`semantic_mapping_version=alarm_mapping_v2`. Migration 007 quarantines every open v1 interval before
v2 capture begins, and pairing queries require the same mapping version. Historical/v1 rows are audit-only.

Validated v2 OUTAGE requests capture the pre-registered `fixed_naive_60m_v1` p50 benchmark in
`etr_candidates` at request receipt time. The benchmark is research-only, is never copied into callback/outbox
payloads, and cannot bypass the send-control gate.

`/api/v1/ais/truth-intervals` returns redacted outage/restore pairing rows for production gate review.
Supported `status` values are `OPEN`, `CLOSED`, `REVIEW`, and `ALL`; the default is `OPEN`.
Responses contain hashed request references, hash/last4 asset references, timestamps, pairing status, safe evidence reason,
and `production_send=blocked`. They must not contain raw meter numbers, PEANO lists, customer identity,
room IDs, tokens, or raw WebEx/Line text.

The public Next.js application is synthetic demo data only. It has no live operator proxy route.

## Prospective v2 lifecycle audit

Run the bounded, authenticated GET-only audit from the repository root:

```powershell
python -m ais_etr ais-v2-lifecycle-audit-once --base-url https://pea-api-intellisense-api.onrender.com
```

The command writes redacted case, summary, operator report, and PEA-CON governance evidence under
`runtime/private/`. RESTORE rows without an open v2 interval remain review/context-only and never
increase model-ready counts. Training and evaluation remain blocked until incident grouping confirms
at least 30 independent prospective incidents and every evaluation row has a numeric shadow prediction
snapshot created before RESTORE.

Evaluate the fixed baseline without retrospective scoring:

```powershell
python -m ais_etr ais-v2-baseline-evaluate-once --base-url https://pea-api-intellisense-api.onrender.com
```

The evaluator groups meter rows within a five-minute outage anchor, retains clean high-error incidents,
rejects prediction-time leakage, and reports interval coverage as unavailable until a pre-registered q10/q90
baseline exists. Each distinct redacted group artifact and metric-semantics combination is recorded once in
an append-only private JSONL registry using a deterministic evaluation ID and SHA-256 artifact hash.
