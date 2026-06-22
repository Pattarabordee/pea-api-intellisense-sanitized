# Ops Controls Blocker Report

- Generated: `2026-06-22T02:52:00Z`
- Mode: `shadow`
- Production send: `blocked`

## Tooling

| Tool | Present |
| --- | --- |
| `pg_dump` | `false` |
| `pg_restore` | `false` |
| `psql` | `false` |

## Local Environment

Only presence is reported. Values are never written.

| Env name | Present |
| --- | --- |
| `DATABASE_URL` | `false` |
| `RESTORE_TEST_DATABASE_URL` | `false` |
| `RENDER_API_KEY` | `false` |

## Status

- Backup/restore drill: `BLOCKED_MISSING_POSTGRES_TOOLS_OR_URLS`
- Render alerts: `MANUAL_CONFIRM_REQUIRED_OR_RENDER_API_KEY_MISSING`
- Key rotation drill: `DEFER_UNTIL_FIRST_REAL_AIS_HIT`

## Required Fix

- Install PostgreSQL client tools if `pg_dump`, `pg_restore`, or `psql` is missing.
- Set `DATABASE_URL` and `RESTORE_TEST_DATABASE_URL` locally only before restore drill.
- Use Render UI/API to confirm alert rules; do not store Render API key in GitHub.
