# Open Questions And Next Steps

## Open Questions

| Question | Why it matters |
| --- | --- |
| Which AIS outage/restore export is authoritative for green-gate evaluation? | Customer-facing truth and model promotion depend on AIS-side labels. |
| Which events are truly production-like Webex events in pilot districts? | Parser and matching quality need real wording, not only sample corpus. |
| Which topology owner can approve feeder/protection mapping? | Feeder fallback and no-match repairs cannot become confident without owner approval. |
| Which callback contract is approved for production? | Auth, retry, idempotency, payload fields, and SLA affect cutover. |
| Which cloud/VM target is approved by PEA? | Render package exists, but production infra remains blocked pending owner/control. |
| Which lifecycle/cause fields can become model features? | PEA/SFSD/ReportPO can help model accuracy only after context approval. |

## Immediate Next Steps

1. Keep cloud/local systems in `shadow` and `production_send=blocked`.
2. Send prioritized AIS truth owner queue for active outage/restore confirmation.
3. Send PEA topology owner queue for downstream protection approval.
4. Install/check local PostgreSQL tools and complete backup/restore drill.
5. Collect or confirm non-smoke cloud AIS request evidence.
6. Refresh green gate after new truth/topology evidence.

## Data Next Steps

- Repair `NO_METER` backlog, prioritizing pilot areas and important AIS assets.
- Add 20-50 representative real Webex messages to parser/evaluation workflow.
- Maintain redacted Webex audit outputs only.
- Resolve prediction/notification history caveat when doing event-level reporting: join to current `outage_events` or explicitly label append-only history.

## Model Next Steps

- Use AIS outage/restore truth as primary target.
- Keep ReportPO/SFSD as context until approved.
- Segment errors by event type, Webex interruption class, match level, active AIS state, feeder, device type, and duration band.
- Continue challenger comparison without overwriting production artifact until gate passes.
- Require at least 30 green rows and passing metrics before any production Auto ETR discussion.

## Cloud/API Next Steps

- Confirm real AIS cloud hit through the Render endpoint, not only local tunnel/runtime.
- Keep `CALLBACK_TRANSPORT=dry_run`.
- Validate API idempotency with duplicate request id.
- Verify `/metrics` exposes only aggregate counts.
- Complete owner approval status file and production gate packet.
- Keep emergency-off path documented and tested.

## Production Promotion Criteria

Production customer-facing Auto ETR remains blocked until all are true:

- Green rows >= 30.
- Green q50 MAE <= 16 minutes.
- Green q10-q90 coverage between 0.75 and 0.90.
- AIS truth owner approves source/semantics.
- PEA topology owner approves impacted path/matching.
- Callback/API owner approves contract and retry policy.
- Operations/security owner approves monitoring, backup/restore, key rotation, incident process, and emergency-off.
- Production infra is approved and not just local tunnel or demo environment.
- First production phase has human review/rollback.

## Suggested Daily Review

1. Read `runtime/cloud_pilot/mvp_daily_qa_report.md`.
2. Read `runtime/green_gate_tracker.md`.
3. Run `python -m ais_etr summary`.
4. Check whether local and cloud inbound counts diverged.
5. Review owner queues and blocker counts.
6. Record decisions in Markdown/CSV, not raw chat or screenshots with secrets.

