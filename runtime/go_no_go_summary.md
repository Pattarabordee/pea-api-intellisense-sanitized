# PEA API Intellisense Go / No-Go Summary

## Decision

| Lane | Decision | Meaning |
| --- | --- | --- |
| Cloud shadow AIS pilot | `GO` | AIS can send pilot API requests into the Render cloud shadow endpoint; PEA can capture, inspect, and export redacted evidence from PostgreSQL. |
| Production infrastructure | `PARTIAL` | Render API, web console, and PostgreSQL are running, but production owner controls, gateway/auth policy, monitoring, backup/restore drill, and key rotation drill still need approval. |
| Customer-facing auto ETR | `NO_GO` | Green auto-ETR gate is not passed and owner approval is still required. |

## Why Pilot Is Ready

- API contract is stable for `POST /api/v1/ais/outage-verifications`, status lookup, health check, and auth-only metrics.
- Valid authenticated request returns `202 Accepted`.
- Unauthorized request returns `401`.
- Render `/health` returns `database=ok`, `mode=shadow`, and `production_send=blocked`.
- Web console reads live cloud API data and no longer falls back to demo data.
- Duplicate `request_id` is handled safely and must not reprocess production send.
- PostgreSQL evidence store is queryable through redacted operator APIs.
- Security/privacy audit is part of final QA.
- Presentation and web demo are packaged for delivery.

## What Is Still Blocked

- `production_send = blocked` remains required in every response/report.
- Auto ETR needs green rows `>=30`, model accuracy/coverage thresholds, and owner approval.
- Production needs PEA-approved API gateway/auth policy, monitoring alerts, backup/restore drill, key rotation drill, retry/dead-letter policy, and named owner approval.
- AIS outage/restore remains customer-facing truth; PEA/SFSD/ReportPO is context/quarantine unless owner-approved.

## Cloud Pilot Commands

Before AIS handoff:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_smoke_check.ps1 `
  -BaseUrl "https://pea-api-intellisense-api.onrender.com" `
  -ApiKey "<cloud pilot key>"
```

After AIS sends real traffic:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_real_hit_check.ps1 `
  -BaseUrl "https://pea-api-intellisense-api.onrender.com" `
  -ApiKey "<cloud pilot key>"
```

Expected high-level result: `status=REAL_AIS_HIT_DETECTED` after AIS hits the cloud endpoint, with `production_send=blocked`.
