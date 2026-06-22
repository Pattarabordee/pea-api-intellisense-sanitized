# Production Send State Machine Runbook

Mode: `shadow`  
Production send: `blocked`

## Current Policy

Default cloud policy is:

```text
PRODUCTION_SEND_MODE=blocked
CALLBACK_TRANSPORT=dry_run
EMERGENCY_OFF=false
```

`emergency_off` overrides every other mode. No mode is allowed to bypass `production_send=blocked` until owner approval and the Auto ETR green gate pass.

## Modes

| Mode | Meaning | Customer-facing send |
| --- | --- | --- |
| `blocked` | Default. Capture evidence only. | No |
| `human_review_only` | Operator may review candidate. | No automatic send |
| `status_only_green_lane` | Green lane may produce status-only dry-run payload. | No |
| `auto_green_lane` | Green lane may produce ETR dry-run payload. | No until separate approval |
| `emergency_off` | Override stop. | No |

## Operator Checks

1. Confirm `/health` returns `mode=shadow` and `production_send=blocked`.
2. Confirm `/metrics` shows `send_control.mode=blocked` or approved test mode.
3. Review `callback_outbox.status`; expected pre-approval value is `DRY_RUN_HELD`.
4. If any report shows `production_send != blocked`, stop and set `EMERGENCY_OFF=true`.

## Approval Gates

Auto ETR remains blocked until all pass:

- Green rows `>=30`
- q50 MAE `<=16 min`
- q10-q90 coverage `0.75-0.90`
- AIS callback contract approved
- PEA/AIS owner approval recorded
- Monitoring, backup/restore, key rotation, and incident response ready
