# Dry-run Callback and DLQ Runbook

Mode: `shadow`  
Production send: `blocked`

## Current Behavior

The Go API creates a `callback_outbox` row for each first-time request. Default status is:

```text
DRY_RUN_HELD
```

This means payload was generated and audited, but no HTTP callback was sent to AIS.

## Retry Policy For Future Real Transport

When real callback transport is approved, use this schedule:

```text
0 min, 1 min, 5 min, 15 min, 60 min
max_attempts = 5
```

After final failure, move to `callback_dead_letters`. Keep payload redacted and keep `production_send=blocked` until approved cutover.

## Operator Response

| Symptom | Action |
| --- | --- |
| `DRY_RUN_HELD` growing | Normal before callback approval |
| `DEAD_LETTER` > 0 | Review error class, do not retry blindly |
| 401/403 callback errors | Rotate/check AIS callback credential |
| 429 callback errors | Respect retry-after and reduce send rate |
| Payload contains raw meter/customer data | Stop, set `EMERGENCY_OFF=true`, run privacy scan |

## Guardrails

- Do not send real callbacks from dry-run output manually.
- Do not paste callback payloads into group chat.
- Do not store API keys, bearer tokens, room IDs, verbatim WebEx text, full PEANO lists, or customer identity in DLQ notes.
