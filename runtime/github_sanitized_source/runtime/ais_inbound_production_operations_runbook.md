# AIS Inbound API Production Operations Runbook

This runbook describes how to operate the AIS inbound outage verification API during pilot-to-production migration.

## Service Contract

- Request endpoint: `POST https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications`
- Status lookup: `GET https://<REDACTED_TUNNEL>/api/v1/ais/outage-verifications/{request_id}`
- Health check: `GET https://<REDACTED_TUNNEL>/health`
- Accepted request HTTP status: `202`
- Auth failure HTTP status: `401`
- Rate limit HTTP status: `429`
- Mode during pilot: `shadow`
- Production send during pilot: `blocked`

## Operator Checks

Run these checks after every endpoint restart or URL change:

```powershell
python -m ais_etr ais-inbound-status
python -m ais_etr ais-inbound-readiness-gate
python -m ais_etr ais-inbound-security-audit
```

Expected pilot result:

- readiness gate has no `FAIL` checks
- security audit status is `PASS`
- `mode = shadow`
- `production_send = blocked`

## First Real AIS Request Procedure

1. Ask AIS to send exactly one request with a unique `request_id`.
2. Run `python -m ais_etr ais-inbound-first-hit-packet`.
3. Check `real_requests > 0`.
4. Confirm the latest real request has no raw meter exposure in reports.
5. Send AIS the status lookup result summary, not internal runtime secrets.
6. Keep production send blocked.

## Incident Response

| Symptom | Likely Cause | Operator Action |
| --- | --- | --- |
| `GET /health` fails | Endpoint or tunnel down | Restart endpoint and rerun readiness gate. |
| AIS receives `401` | Missing/wrong API key | Confirm key out-of-band, never in group chat. |
| AIS receives `400` | Invalid body or timestamp | Ask AIS to share request_id and sanitized payload shape. |
| AIS receives `415` | Wrong content type | Ask AIS to send `Content-Type: application/json`. |
| AIS receives `429` | Too many pilot requests | Follow `Retry-After` header. |
| status lookup returns no match | request_id not stored | Check inbound status report and request log. |

## Data Handling Rules

- Store full inbound requests only through the API pipeline.
- Public reports must show meter hash/last4 only.
- Do not export verbatim WebEx text, room id, token, callback secret, or full meter lists.
- AIS outage/restore remains the customer-facing truth source.
- WebEx remains trigger/device evidence, not restoration truth.
- PEA/SFSD/ReportPO remains context/quarantine unless owner-approved.

## Production Cutover Rule

Production cutover requires explicit owner approval. A passing local readiness gate is not enough.

Before production cutover, the production environment must prove:

- stable HTTPS endpoint
- approved authentication
- secret rotation
- monitoring and alerting
- durable database backup
- callback retry and replay
- privacy/security audit PASS
- production response policy approved by PEA and AIS
