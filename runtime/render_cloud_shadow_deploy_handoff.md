# Render Cloud Shadow Deploy Handoff

Status: `CLOUD_SHADOW_READY_FOR_AIS_TEST`  
Mode: `shadow`  
Production send: `blocked`

## Current Verified State

- Source repo: `https://github.com/Pattarabordee/pea-api-intellisense-sanitized`
- Latest verified commit: see `runtime/render_cloud_shadow_deploy_status.json`
- GitHub Actions: `success`
- Local privacy scan: `PASS`
- Local QA: `WARN` only because local Go CLI is absent; GitHub Actions Go lane passed.

## Render Inputs

Use the root `render.yaml` from the sanitized GitHub repo. It defines:

- `pea-api-intellisense-api`
- `pea-api-intellisense-web`
- `pea-api-intellisense-postgres`

The Postgres database uses Render's current `basic-256mb` instance type. Legacy Postgres plans such as `starter` are not valid for new databases.

The Blueprint pins the public cloud shadow URLs because Render `fromService.property: host` returns a private-network hostname, not a public `https://*.onrender.com` URL:

- API: `https://pea-api-intellisense-api.onrender.com`
- Web console: `https://pea-api-intellisense-web.onrender.com`

This keeps Next.js server-side fetches and CORS aligned during the Render cloud shadow pilot.

Required Render secret:

- `AIS_INBOUND_API_KEY`

The generated cloud pilot key is stored locally at:

```text
D:\PEA Intellisense data\runtime\private\render_cloud_shadow_pilot_key.txt
```

Do not commit this key. Do not send it in group chat. Put it only in Render environment settings and share with AIS through the approved secure channel.

## Render UI Steps

1. Open Render Dashboard.
2. Create a new Blueprint.
3. Connect GitHub repo `Pattarabordee/pea-api-intellisense-sanitized`.
4. Select root `render.yaml`.
5. Confirm services:
   - `pea-api-intellisense-api`
   - `pea-api-intellisense-web`
   - `pea-api-intellisense-postgres`
6. Set `AIS_INBOUND_API_KEY` for both API and web services using the local private key file above.
7. Confirm `AIS_NOTIFICATION_MODE=shadow`.
8. Confirm `RATE_LIMIT_PER_MINUTE=120`.
9. Deploy.

## Post-Deploy Smoke Check

Run after Render gives the API hostname:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_smoke_check.ps1 `
  -BaseUrl "https://<render-api-host>" `
  -ApiKey "<cloud pilot key>"
```

Expected result: `PASS`.

Current cloud smoke result:

- API base URL: `https://pea-api-intellisense-api.onrender.com`
- Status: `PASS`
- Health: `ok`
- Latest smoke request: `AIS-CLOUD-SMOKE-20260622053148`
- Web console live data: `PASS`
- Production send: `blocked`

## AIS Handoff After PASS

Send AIS only:

- Cloud URL: `https://pea-api-intellisense-api.onrender.com/api/v1/ais/outage-verifications`
- Method: `POST`
- Header: `Content-Type: application/json`
- Header: `X-API-Key: <shared through secure channel>`
- Mode: `shadow/pilot only`
- Production send: `blocked`

Copy-paste handoff file:

```text
runtime/ais_cloud_handoff_to_ais.md
```

Do not send internal database URL, raw logs, meter lists, customer identity, or operator notes.

## After AIS Sends Cloud Traffic

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_real_hit_check.ps1 `
  -BaseUrl "https://pea-api-intellisense-api.onrender.com" `
  -ApiKey "<cloud pilot key>"
```

Expected after a real AIS hit: `REAL_AIS_HIT_DETECTED`.

Until AIS sends real cloud traffic, follow:

```text
runtime/cloud_pilot/waiting_for_ais_cloud_pilot.md
```
