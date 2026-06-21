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
6. `tests/test_ais_inbound.py`
7. `tests/test_production_path.py`
8. `runtime/PILOT_COMPLETE_README.md`
9. `runtime/go_no_go_summary.md`
10. `runtime/production_readiness_gate.md`

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

