# Incident Correlation × n8n — Shadow Acceptance Matrix v1

Updated: 2026-08-26 Asia/Bangkok
Scope: safe correlation GET/recovery + multi-channel incident grouping
Mode: SHADOW ONLY

## Global safety assertions for every scenario

Every scenario must preserve all of the following regardless of correlation outcome:

- existing customer ACK does not wait for correlation;
- `mode=shadow`;
- `production_send=blocked`;
- `customer_truth_changed=false` on correlation responses;
- no Operational Incident or Work Order is created by correlation;
- no root cause is confirmed from complaint volume/GIS/text/LLM alone;
- no raw customer name/phone/message, meter IDs, PEANO lists, API secrets, or raw internal cluster IDs appear in correlation output/logs;
- n8n does not calculate topology/cluster identity/score/threshold itself;
- GIS/topology evidence remains context, not live outage confirmation.

## Acceptance scenarios

| ID | Scenario | Setup / evidence | Required safe outcome |
|---|---|---|---|
| IC-N8N-001 | Accepted report while worker pending | One accepted report; durable correlation job `PENDING` | GET=`PENDING`; ACK unchanged; no customer action |
| IC-N8N-002 | Same webhook retry | Retry exact report with same stable ticket/event ID | Existing outage request remains idempotent; no duplicate logical report/cluster inflation |
| IC-N8N-003 | Completed singleton | Worker succeeds; no qualifying relationship | GET=`NO_CLUSTER`; no outage/root-cause claim |
| IC-N8N-004 | Same TX, separate channels | Two accepted reports from different channels resolve to same authoritative TX, compatible time/location | Backend may produce `SUSPECTED_RELATED` according to current Shadow engine; never `confirmed`; n8n does not recalculate |
| IC-N8N-005 | Same feeder, different TX | Reports share feeder but resolve to different TX | Backend decides from versioned score/evidence; test asserts explainability/safety rather than a hard expected threshold before calibration |
| IC-N8N-006 | Strong topology conflict | Reports have fresh authoritative topology contradiction | Must not force merge; strong conflict may hard-veto; zero customer truth change |
| IC-N8N-007 | Same village, multi-feeder ambiguity | Text/admin area overlaps but electrical scope is ambiguous | No forced cluster selection in n8n; backend remains precision-first |
| IC-N8N-008 | Topology unavailable/stale | Location/time available but topology freshness unavailable/stale | Correlation may remain provisional with confidence ceiling; stale topology alone cannot create `HIGH` or hard-veto |
| IC-N8N-009 | Planned outage matched | Report links to authoritative planned-outage notice | Separate planned lane; safe GET may be `PLANNED_OUTAGE_LINKED`; must not increase unplanned-incident confidence |
| IC-N8N-010 | Planned outage uncertain | Planned source inconclusive/unavailable | May correlate provisionally but planned evidence alone cannot produce `HIGH` |
| IC-N8N-011 | Late-arriving report | A report arrives after later reports but occurred_at belongs to same potential occurrence | Time treated as soft feature; re-evaluate graph/revisions; no fixed first-anchor overcount assumption |
| IC-N8N-012 | Rolling incident | Reports accumulate over an extended period with topology support | Connected/versioned correlation may evolve; no immutable first-report time window used as sole grouping rule |
| IC-N8N-013 | Two nearby independent outages | Similar text/admin area but authoritative electrical scopes differ | Prefer false split over false merge; must not merge solely from location/text similarity |
| IC-N8N-014 | Multiple plausible clusters | New report is plausibly related to more than one cluster and evidence is insufficient | `MULTIPLE_CLUSTER_CANDIDATES` or equivalent unresolved backend state; n8n must not choose |
| IC-N8N-015 | Worker retry | Durable job moves `PROCESSING -> RETRYING -> SUCCEEDED` | GET remains safe `PENDING` during retry; final state comes from durable projection |
| IC-N8N-016 | Worker permanent failure | Job reaches `FAILED` | GET=`UNAVAILABLE`; accepted outage receipt remains intact; no outage failure/customer truth rewrite |
| IC-N8N-017 | Process loss / expired lease | Worker dies after claim, lease expires | Job can be reclaimed idempotently; no duplicate logical cluster mutation |
| IC-N8N-018 | Concurrent related reports | Multiple correlation jobs touch shared TX/feeder/upstream scope | Scoped locks/revision checks prevent stale conflicting writes; no whole-system lock required |
| IC-N8N-019 | Merge revision | Previously separate suspected clusters become related after new evidence | New cluster identity supersedes parents with lineage; history retained; n8n receives safe current ref only |
| IC-N8N-020 | Split revision | New authoritative contradiction invalidates previous grouping | Parent history retained; child/current memberships revisioned; no silent overwrite |
| IC-N8N-021 | Reopen/continuation | Evidence supports continuation of a recently closed occurrence | Revisioned reopen/continuation behavior; distinct recurrence must not be silently collapsed |
| IC-N8N-022 | Cross-channel identity ambiguity | Same/similar name, phone-like text, location or LLM similarity appears in different channels without authoritative privacy-safe identity link | Must not deduplicate reporter identity across channels from inferred PII/similarity |
| IC-N8N-023 | Safe cluster response | Active suspected cluster exists | Return safe `cluster_ref`, confidence level and revision only; no raw cluster ID or numeric score |
| IC-N8N-024 | Unknown ticket | Correlation GET for ticket not durably accepted | Safe `NOT_FOUND`; no information leakage |
| IC-N8N-025 | Missing/invalid integration credential | GET without valid integration authentication | HTTP 401; no correlation payload/data leak |
| IC-N8N-026 | Correlation disabled/not captured | Core report exists but feature/store capture unavailable | `UNAVAILABLE`; legacy chatbot flow continues unchanged |

## Calibration-sensitive scenarios

The following must **not** lock an arbitrary numeric expected result before reviewed Shadow calibration data exists:

- same-feeder/different-TX relationship threshold;
- temporal decay/soft-time contribution;
- administrative fallback contribution;
- confidence enter/exit thresholds and hysteresis;
- cluster join threshold.

For these tests, acceptance means deterministic reproducibility, evidence provenance, precision-first safety, no forbidden merge, and correct version/revision behavior. Exact numeric thresholds become acceptance criteria only after a separate calibration decision is approved and versioned.

## n8n E2E execution order

1. Validate auth failure first.
2. Submit one accepted report and confirm legacy ACK.
3. Query correlation immediately and confirm `PENDING` or another safe non-customer-action state.
4. Confirm durable status/retry using the same ticket ID.
5. Submit a controlled second report for a known synthetic/safe topology scenario.
6. Query both tickets and compare safe correlation state/ref/revision.
7. Run duplicate retry and verify counts do not inflate logically.
8. Run conflict/ambiguity scenarios and verify fail-closed behavior.
9. Simulate worker retry/failure in non-production test environment.
10. Export only redacted acceptance evidence and compare against this matrix.

## Exit criteria for the GET/recovery slice

- API/Go CI passes from a clean environment.
- Python guardrail/sanitized-export CI passes.
- Next.js existing build remains green.
- At least IC-N8N-001, 002, 003, 016, 023, 024, 025 are automated at API level.
- Multi-channel topology scenarios are exercised in shadow with synthetic or approved redacted fixtures before any customer-facing capability change.
- No scenario changes `production_send=blocked`.
