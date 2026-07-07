# Production Cutover Gate - AIS ETR / Critical Customer Resilience Platform

Generated: 2026-07-07

## Decision

- Production infrastructure path: `HARDENED_IN_REPO`
- AIS inbound truth capture: `READY_FOR_SHADOW_CLOUD_CAPTURE`
- Auto customer ETR: `BLOCKED_GREEN_GATE`
- Real callback/customer send: `BLOCKED_OWNER_APPROVAL`
- Mode: `shadow`
- Production send: `blocked`

## What Is Now In The Repo

- Go API accepts AIS inbound requests at `/api/v1/ais/outage-verifications`.
- API still enforces auth, rate limit, idempotency, body limit, and redacted storage.
- New `ais_truth_ledger` migration stores AIS outage/restore truth observations.
- New `ais_truth_intervals` migration prepares deterministic derived outage/restore intervals.
- New CLI command `ais-truth-interval-pairing` pairs ready AIS truth observations into derived intervals in dry-run or explicit apply mode.
- API accepts `event_type`, `source_event_id`, `site_id`/`location_id`, `outage_at`, and `restore_at`.
- Metrics now expose `truth_observations`, `truth_review_needed`, `truth_outage_events`, and `truth_restore_events`.
- Metrics also expose `truth_open_intervals` and `truth_closed_intervals` once the pairing worker writes intervals.
- Status lookup returns a redacted `truth_observation` block.
- `production_send` remains blocked at database constraint, API response, send decision, callback outbox, and runbook level.

## Promotion Gates

| Gate | Required State | Current State |
| --- | --- | --- |
| AIS API contract | AIS confirms `OUTAGE`/`RESTORE` field mapping and retry/idempotency behavior. | Pending owner/AIS confirmation. |
| Truth ledger | AIS outage/restore rows are paired into approved site intervals. | Observation table, interval table, and pairing command added; live Postgres integration test pending. |
| Mapping/topology | AIS site/meter refs map to approved PEA meter/protection/feeder refs. | Pending owner approval and repair loop. |
| Green evidence | Green rows >= 30, q50 MAE <= 16 min, q10-q90 coverage 0.75-0.90. | Blocked by current green gate. |
| Callback contract | AIS and PEA approve response payload, retry, timeout, and error handling. | Pending approval. |
| Operations | Monitoring, backup/restore, incident playbook, key rotation, and emergency-off tested. | Docs exist; live owner signoff pending. |
| Business continuity services | Generator inventory, tariff/rate policy, dispatch capacity, and SLA threshold approved. | Pricing scenario exists; official approval pending. |

## Cutover Sequence

1. Deploy sanitized repo to approved cloud/VM target with `PRODUCTION_SEND_MODE=blocked`.
2. Configure secrets out-of-band.
3. Run smoke test and privacy scan.
4. Ask AIS to send one redacted pilot outage event and one restore event.
5. Confirm truth metrics increase and no raw meter/site identifiers appear in status, metrics, reports, or logs.
6. Run `python -m ais_etr ais-truth-interval-pairing --database-url "<postgres-url>"` and review the dry-run report.
7. If dry-run is clean, rerun with `--apply` to upsert derived intervals while `production_send` remains blocked.
8. Repair mapping/topology gaps.
9. Collect green evidence until the production metric gate passes.
10. Get named owner approvals for AIS contract, PEA operations, security, data/model, and callback policy.
11. Only after all gates pass, stage a separate real-callback sender release.

## Hard Stop Conditions

- Green rows remain below threshold.
- `truth_review_needed` grows faster than ready observations.
- AIS sends ambiguous status events instead of explicit outage/restore events.
- Mapping/topology owner does not approve joins.
- Privacy scan finds raw meter/site/customer/chat identifiers.
- Any production send path bypasses `production_send=blocked`.

## Next Engineering Work

1. Add integration tests for the pairing writer against a test PostgreSQL database.
2. Add operator dashboard fields for truth metrics and review queue.
3. Collect live AIS payload samples and Render logs for contract validation.
4. Run Go API tests in CI or any machine with Go 1.23+.
5. Validate that pairing command produces correct open/closed counts on live AIS traffic.
