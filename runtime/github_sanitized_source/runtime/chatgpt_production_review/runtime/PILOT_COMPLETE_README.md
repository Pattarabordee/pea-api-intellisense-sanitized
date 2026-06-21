# PEA API Intellisense Pilot Complete README

Generated for the AIS/PEA controlled pilot delivery.

## Open First

1. `go_no_go_summary.md` - decision summary for what can run now and what is still blocked.
2. `pilot_completion_gate.md` - final gate evidence across API, SQLite, security, delivery pack, and production guardrails.
3. `shareable_pea_pitch_pack.zip` - shareable presentation/demo package.
4. `ais_inbound_api_handoff.md` - AIS-facing API handoff.
5. `ais_inbound_openapi.yaml` or `ais_inbound_postman_collection.json` - API test assets.

## Pilot Ready

- Controlled AIS API pilot can run in `shadow` mode.
- Valid AIS requests return `202 Accepted` and are stored in SQLite evidence.
- Duplicate `request_id` is treated safely and must not trigger reprocessing.
- Status lookup is available for request review.
- Redacted audit export and DB snapshot evidence are queryable.
- Presentation, web game demo, API handoff, scripts, runbook, and QA artifacts are packaged.

## Not Production

- `production_send = blocked` remains mandatory.
- Customer-facing auto ETR is not approved.
- Production infrastructure still needs PEA-approved HTTPS/API gateway, hardened auth, secret rotation, monitoring, durable DB/backup, and named owner approval.
- Green auto-ETR gate remains blocked until enough validated green rows and owner approval exist.

## Operator Commands

- Restart public pilot endpoint:
  `powershell -ExecutionPolicy Bypass -File .\runtime\start_ais_inbound_public_endpoint.ps1`
- Check latest inbound hit status:
  `powershell -ExecutionPolicy Bypass -File .\runtime\ais_inbound_hit_check.ps1`
- Run final Pilot Complete QA:
  `powershell -ExecutionPolicy Bypass -File .\runtime\pilot_complete_final_qa.ps1`
- Rebuild final pilot gate only:
  `python -m ais_etr pilot-completion-gate`

## What To Send AIS

- Endpoint URL and path from the current handoff file.
- Method: `POST`
- Headers: `Content-Type: application/json`, `X-API-Key`, `bypass-tunnel-reminder: true`
- Request body examples from `ais_inbound_api_handoff.md` or Postman collection.
- Timestamp rule: ISO 8601 with timezone, preferred `+07:00` for Thailand events.

Do not send API keys in group chat. Share the pilot key only through the agreed secure channel.

## ChatGPT Co-Pilot Policy

ChatGPT can review sanitized screenshots, contact sheets, redacted API contract wording, scripts, QA checklists, and presentation copy. Do not upload API keys, tokens, WebEx room ids, verbatim WebEx text, full meter/PEANO lists, customer identity, or raw runtime DB. If the browser session stalls twice, continue with local QA and log the fallback.
