# PEA Intellisense × n8n — Incident Correlation Read Contract v1

Updated: 2026-08-26 Asia/Bangkok
Status: FEATURE BRANCH / SHADOW ONLY
Schema: `pea-chatbot-correlation-status.v1`

## Purpose

Expose a read-only, customer-safe Incident Correlation summary to n8n without moving cluster logic, topology scoring, thresholds, or outage truth into n8n.

Correlation remains backend-owned and asynchronous. The existing chatbot v1 ACK/status behavior is unchanged.

## Endpoint

```http
GET /api/v1/chatbot-reports/{ticket_id}/correlation
X-API-Key: <dedicated integration secret>
```

Authentication is the same dedicated outage-integration credential used by the chatbot compatibility adapter. Never put the credential in URL/query string, workflow JSON, Git, logs, screenshots, or chat.

## Non-negotiable semantics

- This endpoint is read-only.
- `bot_action` is always `NO_CUSTOMER_ACTION` in v1.
- `customer_truth_changed` is always `false`.
- `operational_incident_confirmed` is always `false` unless a future separately approved operational-evidence capability changes the contract.
- `root_cause_confirmed` is always `false` in this contract.
- `mode=shadow` and `production_send=blocked` remain mandatory.
- n8n must not calculate cluster identity, numeric correlation thresholds, GIS topology relationship, merge/split decisions, or root cause.
- Raw internal cluster IDs are not exposed; `cluster_ref` is a one-way safe reference.
- Numeric `confidence_score` is intentionally not exposed to n8n v1. The safe response exposes only backend-decided `confidence_level`.

## Safe states

| State | Meaning | n8n v1 behavior |
|---|---|---|
| `NOT_FOUND` | Ticket is not a durably accepted outage report | Keep existing status/not-found flow |
| `UNAVAILABLE` | Correlation capability could not provide a safe result | Do not infer; continue legacy chatbot behavior |
| `PENDING` | Accepted report is queued/processing/retrying | Do nothing customer-facing; optionally poll later |
| `NO_CLUSTER` | Worker completed and no active suspected cluster exists | Do nothing customer-facing |
| `SUSPECTED_RELATED` | Backend suspects this report is related to other report(s) | Internal orchestration/review context only; never claim confirmed outage/root cause |
| `MULTIPLE_CLUSTER_CANDIDATES` | Backend has unresolved multiple candidate clusters | Do not choose a cluster in n8n |
| `PLANNED_OUTAGE_LINKED` | Backend planned-outage lane has an authoritative match | Linkage context only; current customer wording remains governed by the existing approved chatbot contract |

`UNAVAILABLE` may include a non-sensitive `reason_code` for operational handling. n8n must not translate that reason into outage/customer truth.

## Example pending response

```json
{
  "schema_version": "pea-chatbot-correlation-status.v1",
  "ticket_id": "PEA-YYYYMMDD-XXXXXX",
  "found": true,
  "correlation": {
    "available": true,
    "state": "PENDING",
    "confidence_level": "",
    "cluster_ref": "",
    "cluster_revision": 0,
    "lifecycle_state": "",
    "report_count": 0,
    "planned_outage_state": "NOT_CHECKED",
    "engine_version": "incident-correlation-shadow-v1"
  },
  "bot_action": "NO_CUSTOMER_ACTION",
  "customer_truth_changed": false,
  "operational_incident_confirmed": false,
  "root_cause_confirmed": false,
  "mode": "shadow",
  "production_send": "blocked"
}
```

## Example suspected-related response

```json
{
  "schema_version": "pea-chatbot-correlation-status.v1",
  "ticket_id": "PEA-YYYYMMDD-XXXXXX",
  "found": true,
  "correlation": {
    "available": true,
    "state": "SUSPECTED_RELATED",
    "confidence_level": "HIGH",
    "cluster_ref": "correlation_cluster_<safe-ref>",
    "cluster_revision": 3,
    "lifecycle_state": "ACTIVE",
    "report_count": 3,
    "planned_outage_state": "NO_MATCH",
    "engine_version": "incident-correlation-shadow-v1"
  },
  "bot_action": "NO_CUSTOMER_ACTION",
  "customer_truth_changed": false,
  "operational_incident_confirmed": false,
  "root_cause_confirmed": false,
  "mode": "shadow",
  "production_send": "blocked"
}
```

## Recommended n8n polling behavior for Shadow evaluation

1. Existing `POST /api/v1/chatbot-reports` remains the only receipt/ACK path.
2. Do not wait for correlation before acknowledging the customer.
3. After an accepted report, n8n may issue the correlation GET asynchronously for internal logging/evaluation.
4. If state is `PENDING`, use bounded backoff rather than a tight polling loop.
5. If state is `UNAVAILABLE`, stop correlation polling for that attempt and preserve legacy behavior.
6. If state changes meaningfully, record only the safe response/revision; do not recreate the scoring logic in n8n.
7. Webhook/outbox push is a later Phase-5 slice. GET remains the authoritative recovery interface.

## Acceptance criteria for this slice

- Existing chatbot ACK tests remain unchanged and passing.
- Missing/invalid integration auth is rejected.
- Unknown ticket fails safely.
- `PENDING` does not alter customer truth/action.
- Completed singleton returns `NO_CLUSTER`.
- Active backend cluster returns a safe `SUSPECTED_RELATED` summary.
- Raw internal cluster ID is never returned.
- Numeric confidence score is not returned.
- Worker failure returns correlation `UNAVAILABLE` but does not rewrite accepted outage receipt.
- `mode=shadow` and `production_send=blocked` are present on responses.

## Out of scope

- n8n push/webhook delivery
- transactional correlation outbox/DLQ
- customer-facing incident messages
- Operational Incident confirmation
- root-cause confirmation
- work-order creation
- production send enablement
- n8n-side scoring or topology inference
