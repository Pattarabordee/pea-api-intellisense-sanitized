# Guardrails And Governance

## Non-Negotiable Guardrails

- `mode = shadow`
- `production_send = blocked`
- AIS outage/restore is customer-facing truth.
- Webex is trigger/device evidence only.
- PEA/SFSD/ReportPO is context/quarantine unless owner-approved.
- Feeder fallback is shadow/review-only.
- No raw Webex text in shared reports.
- No full meter numbers, PEANO lists, room ids, tokens, secrets, raw customer identity, or customer registration names.
- Runtime SQLite evidence must remain queryable after tests.

## Trust Boundaries

| Boundary | Validation/handling |
| --- | --- |
| AIS inbound request | Request id, timestamp, bounded text fields, API key, body size, rate limit. |
| Webex messages | Persist for idempotency; parse only needed fields; export defaults omit room/actor/raw unless explicit. |
| Registry workbook | `NO_METER` excluded from confident matching. |
| PEA/ReportPO/SFSD | Context/quarantine by default. |
| Notification payloads | Shadow-only; non-shadow payload raises error in Python notifier. |
| Cloud callbacks | Dry-run by default; real transport requires separate gate. |

## Customer-Facing Gate Logic

Green or public-facing ETR needs more than a prediction:

1. Affected AIS customer match exists.
2. Match level is CB/Recloser/Switch/Transformer, not feeder fallback.
3. Webex device state is sustained-like, or active AIS outage is confirmed.
4. AIS truth lane supports evaluation.
5. Model interval is not too wide.
6. Green gate has enough rows and passes metrics.
7. Owners approve topology, callback contract, infrastructure, and production cutover.

## Current Governance State

| Gate | Current state |
| --- | --- |
| Baseline model gate | `gate_fail` |
| Green row count | 0 / 30 |
| Owner approvals | Missing/pending |
| Cloud endpoint package | Ready package |
| Production infrastructure | Blocked |
| Auto ETR | Blocked |
| Privacy red-team scan | PASS |

## Sanitized Review Path

`ais_etr/production_path.py` includes a sanitized export workflow:

- Allows source/test files and selected runtime docs.
- Excludes SQLite, tokens, browser profiles, JSONL logs, private folders, raw spreadsheets, and binary/runtime artifacts.
- Redacts secret-like values, room IDs, meter identifiers, and token patterns.
- Fails if forbidden patterns remain.

Related artifacts:

- `runtime/sanitized_codebase_manifest.json`
- `runtime/sanitized_codebase_bundle.zip`
- `runtime/chatgpt_production_review_audit.md`

## What Not To Do

- Do not turn on production send because cloud health is green.
- Do not treat smoke/demo requests as green evidence.
- Do not train/evaluate customer-facing accuracy on `EVENT_ETR_TIME`.
- Do not use `EVENT_END_TIME` or ticket close as customer restore time.
- Do not expose raw payloads to external reviewers.
- Do not manually approve feeder fallback without topology owner evidence.
- Do not delete runtime evidence to make reports look cleaner.

## Owner Lanes

Current owner work from gate packet:

- AIS truth owner: confirm outage/restore truth for prioritized events.
- PEA topology owner: approve downstream protection mapping.
- Model owner: improve model and uncertainty on green subset.
- Operations owner: approve context use and long/momentary handling.
- Gateway/security owner: approve auth, monitoring, backup/restore, incident process, and emergency-off.

