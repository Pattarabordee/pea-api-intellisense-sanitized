# Production Evidence Tracker

Status: `collecting_cloud_shadow_evidence`  
Mode: `shadow`  
Production send: `blocked`

ใช้ไฟล์นี้เป็น checklist หลักสำหรับ evidence ที่จะนำไปขอ production approval ภายหลัง

## Current Decision

| Lane | Status |
| --- | --- |
| Cloud shadow endpoint | `GO` |
| Real AIS cloud traffic | `WAITING_FOR_AIS` |
| Production infra controls | `PARTIAL` |
| Auto ETR customer-facing | `NO_GO` |

## Evidence Needed Before Production Infra Approval

| Evidence | Status | Source |
| --- | --- | --- |
| Cloud health OK | `PASS` | `/health` |
| Web console uses live data | `PASS` | `production_cloud_real_hit_check.ps1` |
| Real AIS request captured | `WAITING_FOR_AIS` | `production_cloud_real_hit_status.json` |
| Duplicate request safe | `PASS_ON_SMOKE` | `production_cloud_smoke_check.ps1` |
| Privacy scan pass | `PASS` | `production_cloud_privacy_red_team_scan.ps1` |
| Render alerts configured | `PENDING_OPERATOR_SETUP` | Render dashboard |
| PostgreSQL backup drill | `PENDING_LOCAL_TOOLING` | `production_cloud_postgres_backup.ps1` |
| PostgreSQL restore drill | `PENDING_TEST_DATABASE` | `production_cloud_postgres_restore_check.ps1` |
| Key rotation drill | `PENDING_FIRST_AIS_SUCCESS` | `key_rotation_drill.md` |
| Owner approval | `PENDING` | owner approval record |

## Evidence Needed Before Auto ETR

| Gate | Required | Current |
| --- | --- | --- |
| Green rows | `>=30` | pending real pilot cases |
| q50 MAE | `<=16 min` | not approved |
| q10-q90 coverage | `0.75-0.90` | not approved |
| Owner approval | required | pending |

## Redaction Rule

Evidence reports may include only:

- `request_id`
- `received_at`
- `status`
- `callback_status`
- `production_send`
- aggregate counts

Evidence reports must not include API keys, DB URLs, tokens, room ids, verbatim WebEx text, full meter/PEANO, or customer identity.
