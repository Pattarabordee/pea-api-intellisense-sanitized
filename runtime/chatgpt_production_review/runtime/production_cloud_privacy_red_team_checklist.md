# Production Cloud Privacy Red-Team Checklist

Status: cloud shadow path only. `mode = shadow`; `production_send = blocked`.

## Before Uploading To ChatGPT/Gemini/GitHub

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\runtime\production_cloud_privacy_red_team_scan.ps1
```

Allowed upload targets:

- sanitized source bundle
- sanitized screenshots
- redacted API contract
- runbooks and QA reports

Never upload:

- `runtime/private/**`
- SQLite or PostgreSQL dumps
- OAuth token files
- API keys
- WebEx room ids
- verbatim WebEx text
- full meter or PEANO lists
- customer names, phone numbers, addresses, or account identity

## Cloud Data Policy

Cloud phase 1 stores:

- `request_id`
- hashed meter reference
- meter `last4`
- timestamp and timestamp quality
- province/district/subdistrict
- redacted request/response JSON
- evidence status
- ETR candidate status

Cloud phase 1 must not store:

- full meter number
- full PEANO list
- customer identity
- verbatim WebEx text
- tokens or API keys

## Red-Team Prompts

Ask reviewers:

- Can any response reconstruct a full meter number?
- Can any log expose API key, token, room id, or customer identity?
- Can duplicate `request_id` trigger reprocessing?
- Can a bad timestamp silently become trusted?
- Can any path enable customer-facing ETR while the green gate is blocked?

Expected answer for the last item: no. `production_send` must stay `blocked`.
