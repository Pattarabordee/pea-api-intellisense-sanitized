# Waiting For AIS Progress

Generated: `2026-06-22T06:17:28+07:00`  
Mode: `shadow`  
Production send: `blocked`

## Current Cloud Watch

| Item | Status |
| --- | --- |
| API health | `ok` |
| Database | `ok` |
| Web console live data | `PASS` |
| Total cloud requests | `5` |
| Non-smoke requests | `0` |
| Real AIS cloud hit | `NO_REAL_AIS_HIT_YET` |
| Latest redacted request | `AIS-CLOUD-SMOKE-20260622061708` |

## Completed While Waiting

- AIS cloud handoff now asks AIS to report back only `request_id`, sent time, and HTTP status.
- Waiting runbook created at `runtime/cloud_pilot/waiting_for_ais_cloud_pilot.md`.
- Render alert checklist created at `runtime/cloud_pilot/render_alert_checklist.md`.
- AIS test window message created at `runtime/cloud_pilot/ais_test_window_request_th.md`.
- PostgreSQL operator tooling setup created at `runtime/cloud_pilot/postgres_operator_tooling_setup.md`.
- Key rotation drill created at `runtime/cloud_pilot/key_rotation_drill.md`.
- Production evidence tracker created at `runtime/cloud_pilot/production_evidence_tracker.md`.
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
