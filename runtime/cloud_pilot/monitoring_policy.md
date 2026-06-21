# Cloud Monitoring Policy

## Required Signals

- `/health` status and latency
- 2xx, 4xx, 5xx request counts
- 401 unauthorized spike
- 429 rate-limited count
- duplicate `request_id` count
- SQLite write errors
- callback capture/post status
- DB backup success and restore-test status

## Alerts

- Health check fails for 3 consecutive checks
- 5xx count > 0 in 10 minutes
- 401 spikes above agreed AIS test window
- DB backup is older than 24 hours
- Any report shows `production_send` not equal to `blocked`

## Dashboard Note

Do not display API keys, room ids, full meter numbers, PEANO lists, customer identity, or verbatim WebEx text.
