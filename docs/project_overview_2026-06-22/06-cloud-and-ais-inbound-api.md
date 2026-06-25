# Cloud And AIS Inbound API

## Current Cloud Split

There are two evidence lanes:

| Lane | Current state |
| --- | --- |
| Local/runtime AIS inbound | 35 total requests, 4 non-smoke, shadow only. |
| Render cloud report | 5 total requests, 0 non-smoke, health/database ok, shadow only. |

Do not merge these counts. Local evidence proves the processor and SQLite flow. Cloud evidence proves the Render API/web/Postgres path but still lacks a non-smoke cloud hit in the latest report.

## AIS Inbound API Contract

Path:

```text
/api/v1/ais/outage-verifications
```

Core behavior:

- Accepts a request id, meter reference, timestamp, area fields, alarm/cause fields.
- Validates body size, identifier format, timestamp quality, text length, and API key if configured.
- Stores redacted evidence.
- Looks for registry/runtime protection evidence.
- Produces a shadow callback payload.
- Captures or dry-runs callback.
- Keeps `production_send=blocked`.

Trust-boundary defaults in `ais_etr/ais_inbound.py`:

| Limit | Value |
| --- | ---: |
| Max body bytes | 1,000,000 |
| Max request id chars | 128 |
| Max meter chars | 64 |
| Max area chars | 120 |
| Max cause chars | 240 |
| Default match window | 360 minutes |
| Default rate limit | 120/min |
| Future timestamp review threshold | 15 minutes |
| Stale timestamp review threshold | 7 days |

Sensitive keys and meter fields are redacted before logs/reports.

## Go API Production Path

Location: `apps/api-go/`

Endpoints from README:

```http
GET  /health
GET  /metrics
GET  /api/v1/ais/outage-verifications
POST /api/v1/ais/outage-verifications
GET  /api/v1/ais/outage-verifications/{request_id}
```

Key files:

- `apps/api-go/cmd/pea-api-intellisense/main.go`
- `apps/api-go/internal/api/server.go`
- `apps/api-go/internal/storage/postgres.go`
- `apps/api-go/internal/storage/migrations/001_init.sql`
- `apps/api-go/internal/storage/migrations/002_send_controls.sql`
- `apps/api-go/internal/sendcontrol/sendcontrol.go`

Send-control policy modes:

| Mode | Meaning |
| --- | --- |
| `blocked` | Default. No production send. |
| `human_review_only` | Human review required. |
| `status_only_green_lane` | Green rows can produce status-only dry run. |
| `auto_green_lane` | Green rows can produce auto dry run only. |
| `emergency_off` | Override off. |

Even `auto_green_lane` returns dry-run decisions unless separate sender gate allows real transport.

## Next.js Console

Location: `apps/web-next/`

Purpose:

- Executive/operator demo.
- Live data from API when `API_BASE_URL` and `AIS_INBOUND_API_KEY` exist.
- Demo fallback when live API config is missing or fails.

Main files:

- `apps/web-next/app/page.tsx`
- `apps/web-next/app/mission-control.tsx`
- `apps/web-next/lib/api.ts`
- `apps/web-next/lib/demo-data.ts`

The UI deliberately displays guardrails:

- shadow pilot,
- production send blocked,
- Auto ETR not enabled,
- AIS outage/restore remains truth.

## Render Deployment

Blueprint: `render.yaml`

Services:

- `pea-api-intellisense-api`: Docker Go API.
- `pea-api-intellisense-web`: Next.js app.
- `pea-api-intellisense-postgres`: Render Postgres.

Important environment values in blueprint:

- `AIS_NOTIFICATION_MODE=shadow`
- `PRODUCTION_SEND_MODE=blocked`
- `CALLBACK_TRANSPORT=dry_run`
- `EMERGENCY_OFF=false`
- secrets are `sync: false`

## Current Cloud Readiness

Source: `runtime/production_path_readiness_gate.md` and `runtime/cloud_pilot/mvp_daily_qa_report.md`

| Check | Status |
| --- | --- |
| Cloud endpoint package | `READY_FOR_DEPLOYMENT_PACKAGE` |
| Production infrastructure | `BLOCKED_PENDING_OWNER_OR_CONTROL` |
| Auto ETR | `BLOCKED_GREEN_GATE` |
| API health | `ok` |
| Database | `ok` |
| Cloud non-smoke requests | 0 |
| Green rows | 0 / 30 |
| Owner evidence queues | PASS |
| Backup/restore drill | BLOCKED, missing PostgreSQL tools or URLs |
| Privacy red-team scan | PASS |

## CI

Workflow: `.github/workflows/production-cloud-ci.yml`

Jobs:

- Python guardrail test and sanitized export.
- Go API tests.
- Next.js install/audit/build.

CI reinforces the same rule: source bundle must be sanitized, and production send remains blocked until gates pass.

