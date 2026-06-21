# Backup And Restore Commands

Status: `cloud_shadow_postgres`  
Mode: `shadow`  
Production send: `blocked`

The current Render cloud pilot uses PostgreSQL. Use `pg_dump` or Render backup controls. Keep SQLite commands only for local legacy compatibility.

## PostgreSQL Backup

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_postgres_backup.ps1
```

Requires `DATABASE_URL` in the operator environment. Do not paste it into chat or docs.

## PostgreSQL Restore Test

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_postgres_restore_check.ps1 `
  -BackupFile ".\runtime\backups\postgres\<backup>.dump"
```

Requires `RESTORE_TEST_DATABASE_URL`. It must not equal `DATABASE_URL`.

## Redacted Audit Export

Use the operator API/export path only. Public artifacts must not include API keys, DB URLs, room ids, verbatim WebEx text, full meter/PEANO values, or customer identity.

## Legacy SQLite Local Snapshot

Use only for local/dev compatibility, not the Render cloud pilot:

```powershell
python -m ais_etr ais-inbound-db-snapshot --label local_legacy --output runtime/ais_inbound_db_snapshot_latest.md --json-output runtime/ais_inbound_db_snapshot_latest.json
```

Do not restore over a live database until the incident owner approves.
