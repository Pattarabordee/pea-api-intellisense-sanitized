# Render Alert Checklist

Status: `cloud_shadow_alert_setup`  
Mode: `shadow`  
Production send: `blocked`

Create these alerts before wider AIS pilot traffic.

## Required Alerts

| Signal | Suggested trigger | First action |
| --- | --- | --- |
| API service down | Service unavailable or `/health` non-200 for 2 minutes | Check Render service logs and latest deploy. |
| Database error | PostgreSQL connection errors in API logs | Stop cutover testing and check DB status. |
| HTTP `401` spike | More than expected during AIS test window | Confirm AIS uses current key. Do not paste key. |
| HTTP `400` spike | Repeated bad request/timestamp errors | Ask AIS to confirm JSON and ISO 8601 timezone. |
| HTTP `429` spike | Repeated rate-limit responses | Ask AIS to slow retry and reuse same `request_id`. |
| HTTP `5xx` | Any server error during pilot | Check API logs, DB connectivity, and recent deploy. |
| Worker backlog | `pending_worker_traces` grows for more than 30 minutes | Keep production blocked and inspect worker path. |

## Daily Alert Review

- Check Render Events and Logs.
- Check `/health`.
- Check auth-only `/metrics`.
- Confirm no report shows `production_send` other than `blocked`.
- Confirm no logs expose API key, token, room id, full meter number, PEANO list, customer identity, or verbatim WebEx text.

## Owner Note

These alerts are pilot controls. Production infra is still `PARTIAL` until PEA-approved gateway/auth policy, backup/restore drill, key rotation drill, monitoring owner, and operations owner approval are complete.
