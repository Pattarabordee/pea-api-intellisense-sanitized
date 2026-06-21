# Waiting For AIS Cloud Pilot Runbook

Status: `waiting_for_real_ais_cloud_hit`  
Mode: `shadow`  
Production send: `blocked`

## Goal

Keep the cloud pilot healthy while waiting for AIS to send the first real request to the Render endpoint. Do not enable customer-facing Auto ETR.

## AIS Handoff

Send AIS only the safe handoff from:

```text
runtime/ais_cloud_handoff_to_ais.md
```

Share `X-API-Key` through a secure direct channel only. Do not paste the key in group chat, slides, GitHub, or screenshots.

Ask AIS to report back only:

- `request_id`
- sent time
- HTTP status seen by AIS

## Daily Cloud Watch

Run once or twice per day, and again before/after any AIS test window:

```powershell
$key = Get-Content "D:\PEA Intellisense data\runtime\private\render_cloud_shadow_pilot_key.txt" -Raw
powershell -ExecutionPolicy Bypass -File "D:\PEA Intellisense data\runtime\production_cloud_real_hit_check.ps1" `
  -BaseUrl "https://pea-api-intellisense-api.onrender.com" `
  -ApiKey $key
```

Expected before AIS tests:

```text
NO_REAL_AIS_HIT_YET
```

Expected after AIS hits the cloud endpoint:

```text
REAL_AIS_HIT_DETECTED
```

The report must show only redacted fields: `request_id`, `received_at`, `status`, `callback_status`, and `production_send`.

## First Real AIS Hit Checklist

1. Confirm AIS saw HTTP `202`.
2. Run `production_cloud_real_hit_check.ps1`.
3. Confirm `production_send=blocked`.
4. Open the web console and confirm the request is visible.
5. Save the generated real-hit status report.
6. Update Go/No-Go summary only with redacted status.
7. Sync sanitized GitHub.

If AIS sees `401`, the endpoint is reachable but the key is wrong or missing. If AIS sees `400`, the JSON body or timestamp is invalid. If AIS resends the same `request_id`, it must stay duplicate-safe and must not reprocess production send.

## Hardening Queue While Waiting

- Configure Render alerts listed in `runtime/cloud_pilot/monitoring_policy.md`.
- Run backup and restore drill using non-production restore target.
- Run key rotation drill after AIS confirms they can reach the current endpoint.
- Review incident playbook for `401`, `400`, `429`, `5xx`, DB unavailable, and bad timestamp.
- Keep collecting real pilot cases for the green subset.

## Production Boundary

Cloud Shadow Pilot can receive AIS requests now. Customer-facing Auto ETR remains blocked until green rows `>=30`, q50 MAE `<=16 min`, q10-q90 coverage `0.75-0.90`, and owner approval pass.
