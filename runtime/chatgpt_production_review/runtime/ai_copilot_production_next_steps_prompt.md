# Production Next-Steps Review Prompt

You are reviewing the current state of **PEA API Intellisense / AIS ETR** as an external AI product/architecture reviewer.

Public sanitized source repo:
https://github.com/Pattarabordee/pea-api-intellisense-sanitized

Latest known pushed commit:
`6330ad297059dd4e3698b7a83a57bfd4cae59bfa`

## Current State

- Project goal: move from local pilot/demo to production-grade cloud shadow API for AIS-to-PEA outage verification and ETR candidate workflow.
- Current architecture path:
  - Go backend API under `apps/api-go`
  - PostgreSQL durable store with migrations
  - Next.js operator/demo console under `apps/web-next`
  - Render blueprint under `render.yaml`
  - Existing Python AIS ETR semantic layer kept for shadow worker/business logic compatibility
- API contract from AIS view remains unchanged:
  - `POST /api/v1/ais/outage-verifications`
  - `GET /api/v1/ais/outage-verifications/{request_id}`
  - `GET /health`
  - Auth: `X-API-Key`
  - Valid POST returns `202 Accepted`
  - Duplicate `request_id` must be idempotent and not reprocess
- Critical guardrails:
  - `mode = shadow`
  - `production_send = blocked`
  - No customer-facing Auto ETR until green gate and owner approval pass
  - AIS outage/restore remains customer-facing truth
  - WebEx is device/trigger evidence only
  - PEA/SFSD/ReportPO remains context/quarantine unless owner-approved
  - Raw WebEx text, room ids, full meter/PEANO/customer identity, runtime DB, and secrets must not be exposed

## Latest Verification

- Sanitized GitHub repo is public and readable.
- Sanitized export passed scan:
  - included files: 223
  - redactions: 229
  - scan failures: 0
- Python tests passed:
  - `tests/test_production_path.py`
  - `tests/test_ais_inbound.py`
- Next.js:
  - `npm run build` passed
  - `npm audit` found 0 vulnerabilities
- Go:
  - Go API source and tests exist
  - Local machine currently lacks Go CLI; Go test must run in CI/Render/dev machine with Go installed
- Production readiness gate:
  - Cloud endpoint package: `READY_FOR_DEPLOYMENT_PACKAGE`
  - Production infrastructure: `BLOCKED_PENDING_OWNER_OR_CONTROL`
  - Auto ETR: `BLOCKED_GREEN_GATE`
  - `production_send = blocked`

## Question

Please review the repo and current state, then answer:

1. What are the top 5 things we should do next to move toward production safely?
2. What should we **not** do yet, even if executives ask for it?
3. What is the biggest technical risk?
4. What is the biggest governance/security risk?
5. Is deploying the Render cloud shadow API now a good next step? If yes, what must be true before AIS uses it?
6. What should be ready before asking PEA executives for budget/approval?
7. Give a 7-day, 14-day, and 30-day execution plan.

Please be direct. Keep production safety and data redaction above showmanship.
