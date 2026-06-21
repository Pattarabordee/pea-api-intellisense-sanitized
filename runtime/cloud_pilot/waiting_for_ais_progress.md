# Waiting For AIS Progress

Generated: `2026-06-22T06:00:34+07:00`  
Mode: `shadow`  
Production send: `blocked`

## Current Cloud Watch

| Item | Status |
| --- | --- |
| API health | `ok` |
| Database | `ok` |
| Web console live data | `PASS` |
| Total cloud requests | `4` |
| Non-smoke requests | `0` |
| Real AIS cloud hit | `NO_REAL_AIS_HIT_YET` |
| Latest redacted request | `AIS-CLOUD-SMOKE-20260622060012` |

## Completed While Waiting

- AIS cloud handoff now asks AIS to report back only `request_id`, sent time, and HTTP status.
- Waiting runbook created at `runtime/cloud_pilot/waiting_for_ais_cloud_pilot.md`.
- Render alert checklist created at `runtime/cloud_pilot/render_alert_checklist.md`.
- Monitoring policy now references PostgreSQL and real-hit checks.
- Operator runbook and backup commands now point to the current Render + PostgreSQL path.

## Pending Hardening Items

| Item | Status | Blocker / next step |
| --- | --- | --- |
| Render alerts | `PENDING_OPERATOR_SETUP` | Configure in Render dashboard. |
| PostgreSQL backup drill | `PENDING_LOCAL_TOOLING` | Operator machine needs `DATABASE_URL` and `pg_dump`. |
| PostgreSQL restore drill | `PENDING_TEST_DATABASE` | Operator machine needs `RESTORE_TEST_DATABASE_URL` and `pg_restore`; target must not be production DB. |
| Key rotation drill | `PENDING_AIS_WINDOW` | Run after AIS confirms first successful cloud hit. |
| First real AIS hit report | `WAITING_FOR_AIS` | Run `production_cloud_real_hit_check.ps1` after AIS sends traffic. |

## Notes

- One real-hit check returned transient HTTP `520` on `/health`, then smoke check and repeated real-hit check passed. Treat a single `520` as transient if the immediate retry passes.
- Do not enable Auto ETR. Green gate and owner approval are still required.
