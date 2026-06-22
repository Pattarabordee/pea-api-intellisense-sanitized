# Cloud Worker Shadow Loop

- Generated: `2026-06-22T02:14:58Z`
- Status: `DRY_RUN`
- Mode: `shadow`
- Production send: `blocked`
- Pending rows reviewed: `0`

## Decisions

| request_id | evidence | ETR | reason |
| --- | --- | --- | --- |

## Guardrails

- Dry-run is default; `--apply` is required to write append-only worker rows.
- No customer-facing callback is sent.
- Full meter, PEANO lists, customer identity, room IDs, tokens, and verbatim WebEx text are not written.
