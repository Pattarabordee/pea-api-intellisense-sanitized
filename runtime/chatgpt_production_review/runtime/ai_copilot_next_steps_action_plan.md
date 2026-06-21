# AI Co-Pilot Next-Steps Action Plan

Source reviewers: ChatGPT + Gemini.

Claude review: skipped for now.

## Current Decision

Proceed to a **cloud shadow deployment path**, not production Auto ETR.

- Cloud package: ready to deploy.
- Production infra: blocked pending owner/control.
- Auto ETR: blocked by green gate.
- `mode = shadow`
- `production_send = blocked`

## Highest-Priority Next Steps

1. Add GitHub Actions CI:
   - Go `go test ./...`
   - Go `go vet ./...`
   - Python `tests/test_ais_inbound.py`
   - Python `tests/test_production_path.py`
   - Next.js `npm ci`, `npm audit`, `npm run build`
   - sanitized export scan
2. Deploy Render shadow environment:
   - Go API
   - Render Postgres
   - Next.js console
   - env secrets only
3. Add observability:
   - structured logs
   - request correlation ID
   - request_id tracing
   - basic metrics
   - alert/runbook
4. Validate PostgreSQL reliability:
   - fresh migration
   - backup
   - restore
   - duplicate request after restore
5. Validate Go -> PostgreSQL -> Python worker handoff:
   - no dropped `request_id`
   - duplicate not reprocessed
   - worker failure records safe shadow status
6. Run privacy/security red-team:
   - API response scan
   - logs scan
   - UI scan
   - export scan
   - exception path scan

## Explicitly Not Yet

- No Auto ETR.
- No production send.
- No customer-facing PEA truth override.
- No verbatim WebEx/PEANO/customer identity in cloud.
- No additional data-source expansion before cloud shadow baseline is stable.

## 7-Day Target

Cloud shadow environment deployed and testable with synthetic traffic.

Required done:
- CI green.
- Render deploy succeeds.
- `/health` OK.
- valid POST returns `202`.
- invalid auth returns `401`.
- duplicate request is idempotent.
- status lookup works.
- no secret or raw meter/customer leak in public artifacts.

## 14-Day Target

Controlled AIS/staging shadow traffic begins.

Required done:
- API key rotation process.
- access restriction or allowlisting decision.
- basic monitoring/alerting.
- worker handoff validated.
- backup/restore tested.

## 30-Day Target

Executive approval package ready.

Required done:
- shadow accuracy report.
- match/false positive/false negative metrics.
- workflow time-saving evidence versus phone-call process.
- cost projection.
- security/redaction proof.
- governance boundary page.
- budget and owner approval ask.
