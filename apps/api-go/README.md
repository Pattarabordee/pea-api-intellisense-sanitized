# PEA API Intellisense Go API

Production-path shadow API for AIS inbound outage verification.

## Guardrails

- `mode = shadow`
- `production_send = blocked`
- No raw meter, PEANO list, room id, token, or customer identity in responses
- AIS outage/restore remains customer-facing truth
- Auto ETR stays blocked until green gate and owner approval pass

## Environment

```text
PORT=8090
DATABASE_URL=<Render Postgres internal URL>
AIS_INBOUND_API_KEY="<REDACTED_SECRET>" in Render secret/env>
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
GET  /api/v1/ais/outage-verifications
POST /api/v1/ais/outage-verifications
GET  /api/v1/ais/outage-verifications/{request_id}
```

`/metrics` is operator-only and requires `X-API-Key` or `Authorization: Bearer <key>`.
It returns aggregate counts only: total requests, duplicate callbacks, pending worker traces,
`NOT_READY_FOR_AUTO_SEND` count, and `production_send=blocked`.
