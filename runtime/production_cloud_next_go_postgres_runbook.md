# Production Cloud Runbook: Next.js + Go + PostgreSQL

Status: `production path / cloud shadow`. This runbook removes the local-tunnel and always-on-laptop dependency. It does **not** approve customer-facing Auto ETR.

## Target Architecture

```text
AIS
  -> Go API on Render Web Service
  -> Render Postgres durable evidence store
  -> Next.js Operator Console
  -> Python shadow worker path remains reference/compatibility logic
```

## Guardrails

- `mode = shadow`
- `production_send = blocked`
- Auto ETR remains blocked until green rows >= 30, q50 MAE <= 16 minutes, q10-q90 coverage 0.75-0.90, and owner approval pass.
- Cloud phase stores redacted/hashed meter references only.
- Do not upload or commit API keys, tokens, room ids, verbatim WebEx text, full PEANO lists, or customer identity.

## Render Setup

1. Push sanitized source to GitHub.
2. In Render, create a Blueprint from the sanitized repository.
3. Use root `render.yaml`.
4. Create/confirm:
   - `pea-api-intellisense-api`
   - `pea-api-intellisense-web`
   - `pea-api-intellisense-postgres`
5. Set secret env values:

```text
AIS_INBOUND_API_KEY=<new cloud pilot key>
DATABASE_URL=<Render injects this from Postgres>
AIS_NOTIFICATION_MODE=shadow
RATE_LIMIT_PER_MINUTE=120
```

6. After deploy, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_smoke_check.ps1 `
  -BaseUrl "https://<render-api-host>" `
  -ApiKey "<cloud pilot key>"
```

Expected: `PASS`, first POST HTTP `202`, duplicate request safe, status lookup works, `production_send=blocked`.

## Local QA

Before pushing or deploying, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_local_qa.ps1
```

On this laptop, Go may be absent. In that case local QA marks Go as `WARN`; GitHub Actions remains the source of truth for `go test ./...`.

## Observability

Operator endpoints:

```http
GET /health
GET /metrics
```

`/metrics` requires auth and returns aggregate counts only. No raw meter, PEANO list, customer identity, token, room id, or verbatim WebEx text is allowed.

See `runtime/production_cloud_observability_runbook.md`.

## Backup And Restore

Use Render Postgres backup/PITR where available. Also keep an operator export:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_postgres_backup.ps1
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_postgres_restore_check.ps1 `
  -BackupFile ".\runtime\backups\postgres\<backup>.dump"
```

Restore test must run on a non-production database before any live restore.

## Key Rotation

1. Create new `AIS_INBOUND_API_KEY` in Render environment.
2. Redeploy API and web services.
3. Ask AIS to test with new key.
4. Revoke old key after one successful authenticated test.
5. Never paste the key in group chat or decks.

## Incident Playbook

| Incident | First action |
| --- | --- |
| 401 spike | Confirm AIS uses current key. Do not paste key. |
| 429 spike | Keep endpoint alive; ask AIS to slow retry. |
| 5xx | Check Render logs, DB connectivity, and recent deploy. |
| DB unavailable | Stop cutover testing; run restore test on backup. |
| Bad timestamp | Ask AIS to send ISO 8601 with timezone, preferred `+07:00`. |
| Unsafe payload | Keep `production_send=blocked`; export redacted audit only. |

## Owner Approval

Production infra cannot be marked ready until these owners approve:

- PEA API gateway owner
- PEA security owner
- PEA operations owner
- AIS API owner
- Data/model owner
