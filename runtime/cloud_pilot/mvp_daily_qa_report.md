# MVP Daily QA Report

- Generated: `2026-06-22T03:05:47Z`
- Overall: `BLOCKED`
- Mode: `shadow`
- Production send: `blocked`
- Decision: `AUTO_ETR_NO_GO`

## Checks

| Check | Status | Detail |
| --- | --- | --- |
| `cloud_health` | `PASS` | health=ok; database=ok |
| `real_ais_cloud_hit` | `WARN` | real_ais_cloud_requests=0 |
| `green_model_gate` | `BLOCKED` | green_rows=0/30 |
| `owner_evidence_queues` | `PASS` | ais_truth=30; topology=30 |
| `ops_backup_restore_ready` | `BLOCKED` | BLOCKED_MISSING_POSTGRES_TOOLS_OR_URLS |
| `privacy_red_team_scan` | `PASS` | status=PASS |
| `production_guardrail` | `PASS` | production_send=blocked; decision=AUTO_ETR_NO_GO |

## MVP Snapshot

- API health: `ok`
- Database: `ok`
- Total cloud requests: `5`
- Real AIS cloud requests: `0`
- Green rows: `0` / `30`
- AIS truth owner queue: `30` rows
- PEA topology owner queue: `30` rows
- Backup/restore drill: `BLOCKED_MISSING_POSTGRES_TOOLS_OR_URLS`

## Today MVP Work

1. Record demo using `mvp_demo_recording_pack.md` and the web console.
2. Send AIS test-window request to AIS through normal working channel; send key separately.
3. Send owner queues to AIS truth owner and PEA topology owner.
4. Install PostgreSQL client tools before backup/restore drill.

## Guardrails

- This report does not approve customer-facing Auto ETR.
- Do not expose API key, DB URL, token, room ID, verbatim WebEx text, full meter/PEANO, or customer identity.
- Smoke/demo rows do not count toward green model gate.
