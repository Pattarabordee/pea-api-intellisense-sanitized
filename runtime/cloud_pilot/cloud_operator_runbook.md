# Cloud Operator Runbook

Note: this is the older Python-container runbook. For the current Next.js + Go + PostgreSQL Render path, use `runtime/production_cloud_next_go_postgres_runbook.md`.

## Deploy

1. Build the container from the workspace root.
2. Mount `/data` to durable storage.
3. Store `AIS_INBOUND_API_KEY` in a secret manager or protected host environment.
4. Start the container with `AIS_NOTIFICATION_MODE=shadow`.
5. Run `/health` and confirm `production_send=blocked`.

## Restart

```powershell
docker compose -f runtime/cloud_pilot/docker-compose.yml restart
```

## Rotate Key

1. Create a new key in the approved secret store.
2. Update the deployment secret.
3. Restart the container.
4. Ask AIS to test with the new key.
5. Revoke the old key.

## Backup

Use the existing CLI snapshot command against the mounted DB:

```powershell
python -m ais_etr ais-inbound-db-snapshot --label cloud_pilot --output runtime/ais_inbound_db_snapshot_latest.md --json-output runtime/ais_inbound_db_snapshot_latest.json
```

## Restore Test

Copy a snapshot to a test path and run SQLite integrity check before using it.

## Emergency Disable

Keep `AIS_NOTIFICATION_MODE=shadow` and leave `production_send=blocked`. If callback behavior is unsafe, restart with `--no-callback-post` or unset `AIS_CALLBACK_URL`.
