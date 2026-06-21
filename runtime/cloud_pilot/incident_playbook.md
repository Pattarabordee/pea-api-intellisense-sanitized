# Production Incident Playbook

## Auth Failure Spike

- Confirm AIS is using the current key.
- Check whether key rotation just happened.
- Do not paste the key in chat.

## DB Unavailable

- Stop writes if corruption is suspected.
- Take a copy of the DB before repair.
- Run restore test from the latest snapshot.

## Callback Delivery Failure

- Keep `production_send=blocked`.
- Use callback replay in dry-run first.
- Review dead-letter rows before any resend.

## Duplicate Request Storm

- Confirm idempotency still returns duplicate-safe status.
- Rate-limit the source if needed.
- Do not reprocess duplicate `request_id`.

## Bad Timestamp Format

- Return validation error for invalid body.
- Ask AIS to send ISO 8601 with timezone, preferred `+07:00`.

## Model Or Gate Regression

- Immediately keep Auto ETR blocked.
- Rebuild green gate tracker.
- Require owner approval before any green-lane reopening.
