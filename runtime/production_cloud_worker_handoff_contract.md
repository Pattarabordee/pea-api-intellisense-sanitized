# Production Cloud Worker Handoff Contract

Status: first cloud release. Go API receives AIS requests; Python worker remains shadow-only.

Updated 2026-07-07: Go API now stores AIS outage/restore truth observations in `ais_truth_ledger` while keeping production send blocked.

## Current Safe Behavior

When AIS sends a valid request:

1. Go API validates auth, JSON, timestamp, and bounded fields.
2. Go API stores a redacted inbound row in PostgreSQL.
3. Go API stores an AIS truth observation in `ais_truth_ledger`.
4. Go API stores evidence status as `PENDING_WORKER`.
5. Go API stores ETR status as `NOT_READY_FOR_AUTO_SEND`.
6. API returns `202 Accepted`.
7. `production_send` remains `blocked`.

This is intentional. Cloud endpoint can receive and query requests before Auto ETR is allowed.

## Worker Input

Python shadow worker should read only pending rows:

- latest `evidence_traces.trace_status = PENDING_WORKER`
- latest `etr_candidates.status = NOT_READY_FOR_AUTO_SEND`
- request `mode = shadow`
- request `production_send = blocked`

Worker must use hashed/redacted cloud references. Any full meter/PEANO lookup must stay inside approved PEA network or approved secure runtime.

Worker should use `ais_truth_ledger` as the AIS truth-observation stream:

- `event_type = OUTAGE` starts or updates an AIS site outage interval.
- `event_type = RESTORE` closes an AIS site outage interval when paired to the same approved site/meter reference.
- `validation_status = READY_FOR_LEDGER` is eligible for truth-ledger pairing.
- `validation_status <> READY_FOR_LEDGER` remains review-only.
- `STATUS` and `UNKNOWN` events must not train ETR or send customer-facing ETR.

Paired intervals should be written as deterministic derived rows to `ais_truth_intervals`:

- `OPEN` interval: ready `OUTAGE` observation exists, matching restore not yet found.
- `CLOSED` interval: ready `OUTAGE` and `RESTORE` observations pair to the same approved site/meter reference.
- `REVIEW` interval: timing or identifier ambiguity exists.
- Interval rows keep `production_send = blocked`.
- The pairing command uses deterministic interval ids and can upsert a derived interval from `OPEN` to `CLOSED`; raw `ais_truth_ledger` observations remain unchanged.

Dry-run command:

```powershell
python -m ais_etr ais-truth-interval-pairing `
  --database-url "<postgres-url>" `
  --output-json runtime/cloud_pilot/ais_truth_interval_pairing_report.json `
  --markdown-output runtime/cloud_pilot/ais_truth_interval_pairing_report.md
```

Apply command, after reviewing dry-run output:

```powershell
python -m ais_etr ais-truth-interval-pairing `
  --database-url "<postgres-url>" `
  --apply
```

## Worker Output

Worker may append new rows:

- `evidence_traces`
- `etr_candidates`
- `audit_events`

Worker may read `ais_truth_ledger`; it should not mutate prior truth observations. Derived outage/restore intervals are written to `ais_truth_intervals` with deterministic upsert behavior.

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
- AIS outage/restore pairing policy approved
- mapping/topology owner approval for site/meter/protection joins
- named owner approval
- production gateway/auth/monitoring/backup approval
