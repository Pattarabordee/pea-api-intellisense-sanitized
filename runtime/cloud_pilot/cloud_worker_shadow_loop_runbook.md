# Cloud Worker Shadow Loop Runbook

Mode: `shadow`  
Production send: `blocked`

## Purpose

The worker reviews pending cloud requests and appends safe evidence/ETR rows. It does not send customer-facing ETR.

## Dry-run

Use dry-run first:

```powershell
python -m ais_etr cloud-worker-shadow-loop `
  --input-json .\runtime\cloud_pilot\operator_sample.json
```

For live Postgres review, keep `DATABASE_URL` only in local protected environment:

```powershell
python -m ais_etr cloud-worker-shadow-loop `
  --database-url $env:DATABASE_URL
```

## Apply Append-only Worker Rows

Only after dry-run review:

```powershell
python -m ais_etr cloud-worker-shadow-loop `
  --database-url $env:DATABASE_URL `
  --apply
```

## Expected Safe Outcomes

- `SECURE_TOPOLOGY_LOOKUP_REQUIRED`
- `REVIEW_REQUIRED`
- `NOT_READY_FOR_AUTO_SEND`

## Guardrails

- Cloud phase stores hashed/redacted meter references only.
- Full topology lookup needs approved secure data boundary.
- AIS outage/restore remains customer-facing truth.
- WebEx is trigger/device evidence only.
- No verbatim WebEx text, room IDs, API keys, full PEANO lists, or customer identity in worker output.
