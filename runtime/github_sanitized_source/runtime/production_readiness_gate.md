# Production Readiness Gate

Production AIS send remains blocked unless the green subset passes metric gates and receives human approval.

## Gate

- Green rows: 0
- Green q50 MAE:  min
- Green q10-q90 coverage: 
- Gate target: q50 MAE <= 16 min and q10-q90 coverage 0.75-0.9
- Status: blocked_no_green_subset

## Allowed Actions

- `green_auto_candidate`: shadow auto ETR candidate only until production approval.
- `amber_human_review`: status-only or human-approved message.
- `red_blocked`: no customer send.
- `monitor_only`: parser/matching monitoring only.

## Guardrails

- AIS outage/restore remains the only customer-facing truth label.
- WebEx is trigger/device evidence only.
- PEA/SFSD/ReportPO quarantine rows are not used in metrics, features, fallback, or truth.
- No production AIS send is performed by these commands.
- Outputs omit source chat bodies, room identifiers, credentials, customer meter identifier lists, and customer identity fields.
