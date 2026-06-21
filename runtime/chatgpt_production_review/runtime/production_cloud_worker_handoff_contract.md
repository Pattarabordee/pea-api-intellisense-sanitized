# Production Cloud Worker Handoff Contract

Status: first cloud release. Go API receives AIS requests; Python worker remains shadow-only.

## Current Safe Behavior

When AIS sends a valid request:

1. Go API validates auth, JSON, timestamp, and bounded fields.
2. Go API stores a redacted inbound row in PostgreSQL.
3. Go API stores evidence status as `PENDING_WORKER`.
4. Go API stores ETR status as `NOT_READY_FOR_AUTO_SEND`.
5. API returns `202 Accepted`.
6. `production_send` remains `blocked`.

This is intentional. Cloud endpoint can receive and query requests before Auto ETR is allowed.

## Worker Input

Python shadow worker should read only pending rows:

- latest `evidence_traces.trace_status = PENDING_WORKER`
- latest `etr_candidates.status = NOT_READY_FOR_AUTO_SEND`
- request `mode = shadow`
- request `production_send = blocked`

Worker must use hashed/redacted cloud references. Any full meter/PEANO lookup must stay inside approved PEA network or approved secure runtime.

## Worker Output

Worker may append new rows:

- `evidence_traces`
- `etr_candidates`
- `audit_events`

Worker must not update old evidence in place. Append-only history keeps audit readable.

Allowed statuses before owner approval:

- `NO_PEA_EVIDENCE_FOUND`
- `CONFIRMED_PEA_OUTAGE`
- `AIS_EQUIPMENT_OR_BACKUP`
- `REVIEW_REQUIRED`
- `NOT_READY_FOR_AUTO_SEND`

Required on every worker output:

- `mode = shadow`
- `production_send = blocked`
- `production_gate = blocked_green_gate` unless owner-approved green gate is passed

## Failure Behavior

If worker fails, timeout, or cannot trace evidence:

- keep latest evidence status `PENDING_WORKER` or append `REVIEW_REQUIRED`
- keep latest ETR status `NOT_READY_FOR_AUTO_SEND`
- write an `audit_events` row with redacted error category
- do not send callback/customer-facing ETR

## Promotion Boundary

Do not connect the worker to production callback sending until:

- green rows `>=30`
- q50 MAE `<=16 min`
- q10-q90 coverage `0.75-0.90`
- named owner approval
- production gateway/auth/monitoring/backup approval
