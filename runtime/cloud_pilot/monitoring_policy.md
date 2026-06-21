# Cloud Monitoring Policy

## Required Signals

- `/health` status and latency
- 2xx, 4xx, 5xx request counts
- 401 unauthorized spike
- 429 rate-limited count
- duplicate `request_id` count
- PostgreSQL connection/write errors
- callback capture/post status
- DB backup success and restore-test status
- real AIS cloud hit status from `runtime/production_cloud_real_hit_check.ps1`

## Alerts

- Health check fails for 3 consecutive checks
- 5xx count > 0 in 10 minutes
- 401 spikes above agreed AIS test window
- DB backup is older than 24 hours
- Any report shows `production_send` not equal to `blocked`
- `pending_worker_traces` grows for more than 30 minutes

## Dashboard Note

Do not display API keys, room ids, full meter numbers, PEANO lists, customer identity, or verbatim WebEx text.

Detailed Render alert setup lives in `runtime/cloud_pilot/render_alert_checklist.md`.
