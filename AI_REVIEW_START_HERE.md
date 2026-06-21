# AI Review Start Here

This repository is a sanitized source export for the PEA API Intellisense / AIS ETR pilot.

## Current Truth

- Mode: `shadow`
- Production sends: `production_send = blocked`
- AIS outage/restore remains the customer-facing truth source.
- PEA/WebEx/PowerBI context is evidence or quarantine context unless owner-approved.
- Auto ETR is not production-live.

## What To Review First

1. `README_AIS_ETR_MVP.md`
2. `AGENTS.md`
3. `ais_etr/ais_inbound.py`
4. `ais_etr/production_path.py`
5. `ais_etr/cli.py`
6. `apps/api-go/README.md`
7. `apps/api-go/internal/api/server.go`
8. `apps/api-go/internal/storage/postgres.go`
9. `apps/api-go/internal/storage/migrations/001_init.sql`
10. `apps/web-next/app/mission-control.tsx`
11. `render.yaml`
12. `tests/test_ais_inbound.py`
13. `tests/test_production_path.py`
14. `runtime/PILOT_COMPLETE_README.md`
15. `runtime/go_no_go_summary.md`
16. `runtime/production_path_readiness_gate.md`
17. `runtime/pea_api_intellisense_technical_brief.md`
18. `runtime/pea_api_intellisense_pitch_answers.md`

## Guardrails

Do not suggest enabling production Auto ETR until these pass:

- green rows `>=30`
- q50 MAE `<=16 min`
- q10-q90 coverage `0.75-0.90`
- owner approval
- production-grade gateway/auth/monitoring/backup/restore

## Sanitization Note

This export was generated with `python -m ais_etr export-sanitized-codebase`.
Runtime secrets, OAuth tokens, DB files, JSONL logs, raw WebEx text, room ids, full meter/PEANO lists, and customer identity are intentionally excluded or redacted.
