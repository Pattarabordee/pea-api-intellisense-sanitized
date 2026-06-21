# Production Cloud Observability Runbook

Status: cloud shadow path only. `mode = shadow`; `production_send = blocked`.

## Health And Metrics

- Public liveness: `GET /health`
- Operator metrics: `GET /metrics` with `X-API-Key` or `Authorization: Bearer <pilot key>`
- AIS contract endpoints stay unchanged:
  - `POST /api/v1/ais/outage-verifications`
  - `GET /api/v1/ais/outage-verifications/{request_id}`

`/metrics` returns aggregate counts only:

- `total_requests`
- `duplicate_callbacks`
- `pending_worker_traces`
- `not_ready_etr`
- `callback_counts`
- `latest_received_at`
- `production_send = blocked`

It must not return raw meter numbers, PEANO lists, customer identity, tokens, room ids, or verbatim WebEx text.

## Required Render Alerts

Create alerts before AIS uses the cloud URL:

- API service down or `/health` non-200 for 2 minutes.
- PostgreSQL connection errors in logs.
- HTTP 401 spike: possible wrong key or abuse.
- HTTP 429 spike: duplicate storm or client retry issue.
- HTTP 400 spike: bad timestamp/body format from AIS.
- `pending_worker_traces` growing for more than 30 minutes.
- `not_ready_etr` is expected before Auto ETR gate, but must remain visible.

## Structured Log Events

The Go API emits JSON logs. Safe fields only:

- `request_id`
- `meter_last4`
- `mode`
- `production_send`
- error category

Forbidden in logs:

- full meter number or PEANO list
- API key or token
- room id
- verbatim WebEx text
- customer identity

## Daily Operator Check

1. Open Render service health.
2. Call `/health`.
3. Call `/metrics` with operator key.
4. Confirm latest request appears in operator console.
5. Confirm backup job ran or run `runtime/production_cloud_postgres_backup.ps1`.
6. Confirm `production_send = blocked` in API, console, and reports.

## Promotion Boundary

Cloud endpoint can be production-grade for receiving AIS requests before Auto ETR is live.
Customer-facing Auto ETR remains blocked until:

- green rows `>=30`
- q50 MAE `<=16 min`
- q10-q90 coverage `0.75-0.90`
- owner approval
- production gateway/auth/monitoring/backup approved
