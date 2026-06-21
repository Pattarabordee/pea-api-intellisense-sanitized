# AIS Inbound API Production Migration Checklist

Current pilot base URL: `https://<REDACTED_TUNNEL>`

This document is a migration checklist only. It does not approve production sending.

## Current Pilot State

- API version: `v1`
- Schema version: `2026-06-20`
- Current mode: `shadow`
- Current production_send: `blocked`
- Current hosting: local pilot tunnel
- Current authentication: shared pilot API key
- Current storage: local SQLite runtime evidence
- Current pilot evidence: real AIS pilot requests have reached the endpoint and are stored in the shadow evidence tables
- Current production path package: provider-neutral container package under `runtime/cloud_pilot`
- Current ChatGPT review path: sanitized source bundle only, not raw workspace

## Production Entry Criteria

Production must remain blocked until every item below has an owner and an evidence link.

| Area | Required Control | Evidence Needed | Status |
| --- | --- | --- | --- |
| Endpoint | Stable HTTPS domain or API gateway URL | Production URL and DNS/TLS owner | `pending` |
| Network | AIS and PEA agree on connectivity path | Allowlist, VPN, private link, or gateway policy | `pending` |
| Authentication | Replace or harden shared pilot key | mTLS, signed requests, OAuth client credentials, or API gateway key with rotation | `pending` |
| Secret management | Store secrets outside source/runtime reports | Secret manager path and rotation procedure | `pending` |
| Database | Durable store and backup policy | Backup/restore test evidence | `pending` |
| Observability | Health, error, latency, and request-volume monitoring | Dashboard and alert policy | `pending` |
| Replay/retry | Callback retry and idempotency policy | Retry schedule, dead-letter review, replay command | `pending` |
| Data privacy | Public docs and reports pass leakage scan | Security audit report with `PASS` | `pending` |
| Model/ETR | Customer-facing ETR gate approved | Green subset gate and owner approval | `pending` |
| Operations | Runbook and on-call owner assigned | Contact path and escalation rule | `pending` |
| ChatGPT co-pilot | Sanitized codebase bundle only | Manifest and scan result with `PASS` | `pending` |

## Production Blockers Today

- Real AIS pilot requests have reached the endpoint, but that only proves pilot connectivity and evidence capture.
- The endpoint still runs through a local pilot tunnel.
- Automatic production ETR sending is not approved.
- Final authentication and secret rotation are not approved.
- Final monitoring and SLA are not approved.
- Durable production database, backup/restore, and named gateway owner are not approved.
- Auto ETR remains blocked until the green gate has enough validated rows and owner approval.
- Cloud package exists for review/deployment, but no approved cloud endpoint URL is live yet.
- ChatGPT must receive only the sanitized codebase bundle, not raw runtime files.

## Recommended Promotion Path

1. Keep capturing controlled AIS pilot requests and verify stored status lookup/audit export.
2. Run the security audit and confirm `PASS`.
3. Move the endpoint behind a stable PEA-approved HTTPS gateway.
4. Configure production-grade authentication and secret rotation.
5. Configure durable database backup and restore.
6. Configure monitoring and alerting.
7. Export sanitized codebase bundle for ChatGPT/architecture review.
8. Run a shadow soak period with AIS real requests.
9. Approve only status-only or green-lane responses first.
10. Keep p50 ETR production blocked until the model gate is approved.
