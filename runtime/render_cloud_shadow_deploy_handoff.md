# Render Cloud Shadow Deploy Handoff

Status: `READY_FOR_RENDER_LOGIN_OR_API_KEY`  
Mode: `shadow`  
Production send: `blocked`

## Current Verified State

- Source repo: `https://github.com/Pattarabordee/pea-api-intellisense-sanitized`
- Latest verified commit: `99502abaf74427576b6b1b0da33e1a766de97546`
- GitHub Actions: `success`
- Local privacy scan: `PASS`
- Local QA: `WARN` only because local Go CLI is absent; GitHub Actions Go lane passed.

## Render Inputs

Use the root `render.yaml` from the sanitized GitHub repo. It defines:

- `pea-api-intellisense-api`
- `pea-api-intellisense-web`
- `pea-api-intellisense-postgres`

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

## AIS Handoff After PASS

Send AIS only:

- Cloud URL: `https://<render-api-host>/api/v1/ais/outage-verifications`
- Method: `POST`
- Header: `Content-Type: application/json`
- Header: `X-API-Key: <shared through secure channel>`
- Mode: `shadow/pilot only`
- Production send: `blocked`

Do not send internal database URL, raw logs, meter lists, customer identity, or operator notes.
