# Cloud Operator Runbook

Status: `cloud_shadow_render_postgres`  
Mode: `shadow`  
Production send: `blocked`

For the current Next.js + Go + PostgreSQL Render path, use `runtime/production_cloud_next_go_postgres_runbook.md` as the main runbook. This file keeps the short operator checklist.

## Deploy

1. Deploy from Render Blueprint at the sanitized GitHub repo.
2. Confirm `pea-api-intellisense-api`, `pea-api-intellisense-web`, and `pea-api-intellisense-postgres` are healthy.
3. Store `AIS_INBOUND_API_KEY` only in Render environment settings.
4. Keep `AIS_NOTIFICATION_MODE=shadow`.
5. Keep `PRODUCTION_SEND_MODE=blocked`, `CALLBACK_TRANSPORT=dry_run`, and `EMERGENCY_OFF=false`.
6. Run `/health` and confirm `database=ok`, `mode=shadow`, and `production_send=blocked`.

## Restart

Restart the affected Render service from the Render dashboard. After restart, run `runtime/production_cloud_smoke_check.ps1`.

## Rotate Key

1. Create a new key in the approved secret store.
2. Update Render environment variable `AIS_INBOUND_API_KEY` for API and web.
3. Redeploy affected services.
4. Run smoke check.
5. Ask AIS to test with the new key.
5. Revoke the old key.

## Backup

Use PostgreSQL backup:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_postgres_backup.ps1
```

## Restore Test

Restore only into a non-production database:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_postgres_restore_check.ps1 `
  -BackupFile ".\runtime\backups\postgres\<backup>.dump"
```

## Emergency Disable

Set `EMERGENCY_OFF=true`, keep `AIS_NOTIFICATION_MODE=shadow`, and leave `production_send=blocked`. If callback behavior is unsafe, unset callback configuration and redeploy.

## Worker And Send Controls

- State machine: `runtime/cloud_pilot/production_send_state_machine_runbook.md`
- Worker: `runtime/cloud_pilot/cloud_worker_shadow_loop_runbook.md`
- Dry-run callback and DLQ: `runtime/cloud_pilot/dry_run_callback_dlq_runbook.md`

## Waiting For AIS

Use `runtime/cloud_pilot/waiting_for_ais_cloud_pilot.md`.
