# Backup And Restore Commands

Note: these commands are for the older SQLite cloud pilot path. The current Render Postgres path uses `pg_dump`/Render backup controls. See `runtime/production_cloud_next_go_postgres_runbook.md`.

## Snapshot

```powershell
python -m ais_etr ais-inbound-db-snapshot --label cloud_pilot --output runtime/ais_inbound_db_snapshot_latest.md --json-output runtime/ais_inbound_db_snapshot_latest.json
```

## Audit Export

```powershell
python -m ais_etr ais-inbound-audit-export --output runtime/ais_inbound_audit_export.csv --markdown-output runtime/ais_inbound_audit_export.md
```

## Restore Test

1. Copy a snapshot to a test DB path.
2. Run SQLite integrity check on the test DB.
3. Run `python -m ais_etr ais-inbound-status --output runtime/ais_inbound_status_report.md`.
4. Confirm request/callback rows are queryable.

Do not restore over the live DB until the incident owner approves.
