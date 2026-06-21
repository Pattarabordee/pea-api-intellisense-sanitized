# AI Co-Pilot Consultation Summary: Production Next Steps

Date: 2026-06-21

Input prompt: `runtime/ai_copilot_production_next_steps_prompt.md`

## Status

- ChatGPT: completed.
- Gemini: completed.
- Claude: skipped for now per user instruction.

## Consensus So Far

ChatGPT and Gemini agree on the core direction:

1. Deploy Render cloud shadow API next, but keep `mode=shadow` and `production_send=blocked`.
2. Do not enable customer-facing Auto ETR.
3. Add CI before treating Go API as production boundary.
4. Validate PostgreSQL migration, backup, restore, and duplicate/idempotency behavior.
5. Add observability before AIS uses the endpoint.
6. Prove redaction and no-leak behavior in API responses, logs, UI, exports, and exception paths.
7. Prepare executive approval package from evidence, not architecture alone.

## Highest-Priority Next Work

1. GitHub Actions CI:
   - Go test/vet
   - Python tests
   - Next build/audit
   - sanitized export scan
2. Render deployment dry run:
   - API
   - PostgreSQL
   - Next.js console
   - env/secret setup
3. Observability:
   - structured logs
   - request correlation ID
   - metrics endpoint or log-derived metrics
   - alerting/runbook
4. PostgreSQL reliability:
   - migration test
   - backup/restore test
   - duplicate request restore test
5. Worker handoff:
   - Go writes request
   - Python worker processes once
   - failed worker records safe `NOT_READY_FOR_AUTO_SEND`
   - no dropped `request_id`
6. Red-team privacy scan:
   - verbatim WebEx text
   - room IDs
   - PEANO/meter/customer identity
   - API keys/secrets
   - DB URL

## Do Not Do Yet

- Do not enable Auto ETR.
- Do not allow production sends.
- Do not let PEA override AIS customer-facing outage truth.
- Do not add new data sources before the cloud shadow baseline is stable.
- Do not expose internal confidence scores to customers.

## Suggested 7/14/30-Day Plan

### 7 Days

- Add CI/CD.
- Run Go tests in CI.
- Deploy Render shadow environment.
- Verify `/health`, valid POST, duplicate POST, status lookup.
- Add structured logs and basic metrics.
- Run redaction leak test.

### 14 Days

- Start controlled AIS staging/shadow traffic.
- Validate Go -> PostgreSQL -> Python worker handoff.
- Monitor idempotency and worker retry behavior.
- Run migration/backup/restore tests.
- Add operator console quarantine/review state.

### 30 Days

- Produce shadow accuracy report.
- Produce security/redaction evidence.
- Produce workflow time-saving evidence versus phone-call process.
- Produce cost projection.
- Produce executive approval pack and budget ask.

## Decision For Current Workstream

Proceed without Claude review for now. Treat the next implementation batch as:

1. CI/CD gate first.
2. Render shadow deploy second.
3. Observability, migration/restore, worker handoff, and privacy red-team before AIS production-like use.
4. Auto ETR remains blocked.
