# PEA Intellisense — Incident Correlation Shadow v1

Updated: 2026-08-26 Asia/Bangkok
Status: DESIGN LOCKED FOR PHASED IMPLEMENTATION
Rollout: SHADOW FIRST

## Purpose

Incident Correlation determines whether multiple accepted outage reports from different chats/channels are likely related to the same incident occurrence. It must not convert complaint volume, GIS topology, semantic similarity, or AI inference into outage confirmation or confirmed root cause.

## Core semantics

- Every accepted report remains an independent immutable report event.
- Backend creates immutable internal `report_id`; external `ticket_id`, channel and event identifiers are references/idempotency keys only.
- Reports may be grouped into a `Suspected Incident Cluster`; tickets are never merged or deleted.
- `HIGH` means high confidence that reports are related, not that outage/cause/equipment failure is confirmed.
- Operational confirmation is a separate `Operational Incident` object linked only by approved operational evidence.
- Root cause is separate from incident correlation. `root_cause_hypothesis` remains suspected until evidence hierarchy permits confirmation.

## Evidence hierarchy and scoring

Primary evidence is electrical topology + time + location.

Topology hierarchy:
1. Same TX: strongest positive evidence.
2. Same feeder: medium positive evidence.
3. Shared upstream protection/recloser: possible common-cause evidence.
4. Text/landmark/channel: supporting evidence only.

Time is a soft scoring feature, not a hard time-window cutoff.

The engine uses deterministic, explainable, versioned scoring. Each relationship stores feature contributions and negative evidence. Initial weights/thresholds are explicitly uncalibrated Shadow parameters and must be calibrated from reviewed data before enforcement.

Strong authoritative topology contradiction may hard-veto a relationship. Stale/unknown-freshness topology cannot independently create `HIGH` or hard-veto. If topology is unavailable, correlation may continue provisionally with a confidence ceiling and must be re-evaluated when the source returns.

The system is precision-first: false merge is treated as more dangerous than false split.

## Confidence

Store both:
- `confidence_score` for deterministic ranking/calibration;
- `confidence_level` (`LOW`, `MEDIUM`, `HIGH`) for humans/downstream systems.

Confidence changes use enter/exit thresholds and stability/hysteresis. Strong authoritative contradiction can override hysteresis.

Complaint volume is supporting evidence only. Preserve both `raw_report_count` and `unique_reporter_count`; unique reporters must be deduplicated across channels only when a privacy-safe authoritative identity link exists. Never infer cross-channel identity from name, phone, text, location or LLM similarity.

## Relationship graph and clusters

Persist versioned pairwise `report_relationship` edges and derive clusters from the graph.

- A report has at most one active cluster membership at a given revision.
- Membership history is versioned and never overwritten.
- Cluster IDs are immutable identities.
- Merge creates a new cluster ID and supersedes parents.
- Split creates new child IDs and marks the parent split.
- True continuation may reopen the same cluster with a new revision.
- Multiple plausible cluster candidates remain `MULTIPLE_CLUSTER_CANDIDATES`; do not assign permanently until evidence is sufficient.

Cluster structure is dynamic and may merge/split/reopen as evidence changes. Every change requires revision history and provenance.

## Planned outage interaction

Planned outage is a separate lane.

- `PLANNED_OUTAGE_MATCHED` links reports to the notice and must not increase confidence of a suspected unplanned incident.
- `PLANNED_OUTAGE_UNCERTAIN` may participate provisionally but cannot independently produce `HIGH`.
- When planned-outage evidence changes, impacted reports/clusters are re-evaluated with revisions.

## Root cause and recurrence

A cluster describes incident occurrence, not root cause.

- Keep multiple ranked `root_cause_hypothesis` candidates (`PRIMARY`, `ALTERNATIVE`, `REJECTED`).
- Complaint count, GIS, semantic similarity and AI inference cannot confirm root cause.
- Confirmation requires approved operational evidence hierarchy (e.g. authoritative SCADA/OMS, field confirmation, work-order/fault record, or controlled operator confirmation referencing such evidence).
- Corrected confirmed causes create superseding revisions; history is never deleted.
- Recurring equipment/common-cause patterns may link occurrence-specific hypotheses to an `equipment_issue_thread` and create `MAINTENANCE_REVIEW_CANDIDATE`, never an automatic work order.

## Lifecycle and operator workflow

Cluster lifecycle: `ACTIVE -> QUIET -> CLOSED`, with revisioned `REOPENED` when evidence supports continuation. A distinct recurrence creates a new cluster linked via recurrence/related-cluster metadata.

`HIGH` creates `INCIDENT_REVIEW_CANDIDATE`, not Operational Incident/Work Order.

Operator labels are structured ground truth:
- `SAME_INCIDENT`
- `DIFFERENT_INCIDENT`
- `INSUFFICIENT_EVIDENCE`

Labels feed offline calibration datasets only; no automatic online learning.

Manual correction uses controlled override actions (`FORCE_LINK`, `FORCE_UNLINK`, `FORCE_SPLIT`, `FORCE_MERGE`) with reason/evidence/revision/audit. High-impact overrides require tiered approval. New authoritative operational evidence may conflict with/supersede manual override through a controlled revisioned process.

## Processing and concurrency

Only reports that pass preflight and are durably `ACCEPTED` enter correlation.

Customer ACK must not wait for correlation. Correlation runs as an asynchronous durable job with lifecycle such as `PENDING -> PROCESSING -> RETRYING -> SUCCEEDED/FAILED`, bounded retries/backoff and idempotent replay.

Candidate/evidence computation may run concurrently, but mutations use transaction + idempotency + revision checks/locks scoped to affected cluster/subgraph. Stale writers use optimistic concurrency (`expected_revision` mismatch => recompute from latest state).

Evidence changes trigger impact-scoped recomputation. Major engine/rule versions use controlled batch dry-run/Shadow comparison.

## Versioning and rollout

Only one `active_engine_version` is authoritative per scope. Other versions may dual-evaluate in Shadow.

Major release path:
1. side-by-side Shadow comparison;
2. reviewed quality/safety metrics;
3. canary;
4. explicit atomic promote;
5. rollback available without deleting decision history.

Rollback of a degraded engine includes impact analysis and corrective state revisions computed by the stable version.

Shadow exit requires representative data plus metric-based acceptance. Precision is prioritized over recall. Safety floors include zero known false merge in reviewed high/critical cases, zero LLM-only `HIGH`, zero merge across strong authoritative topology conflict, zero PII/secret leakage, and full explainability/provenance for merge/split/HIGH decisions.

## APIs and n8n boundary

Correlation source of truth is PEA Intellisense Backend. n8n never computes cluster identity/topology correlation itself.

Planned interface:
- dedicated authoritative correlation GET endpoint per report/ticket;
- legacy chatbot v1 semantics remain unchanged;
- new clients may request safe correlation summary only after explicit capability/version negotiation.

Customer/n8n safe state machine may include:
- `PENDING`
- `NO_CLUSTER`
- `SUSPECTED_RELATED`
- `MULTIPLE_CANDIDATES`
- `PLANNED_OUTAGE_LINKED`
- `OPERATIONAL_INCIDENT_LINKED`

Internal/operator API may expose detailed score breakdown, evidence, topology hypothesis, revisions and lineage. Customer-facing flows receive controlled template/action only.

Meaningful transitions may be pushed to n8n, while GET remains authoritative recovery. Delivery design is transactional outbox + at-least-once, idempotent event IDs, revision/state-version checks, HMAC-signed webhook with separate outbound credential, durable DLQ and latest-state `RECOVERY_SYNC` recovery.

## Privacy, retention and audit

Correlation layer should avoid PII. Raw customer content and identity data use shorter/configurable retention than derived non-PII decision metadata. Privacy deletion removes/anonymizes raw/PII while retaining only permitted non-reversible derived audit records.

Audit is append-only/tamper-evident. Merge/split, override, approval, engine promotion/rollback, DLQ replay, operational linkage and cause correction create new records, never edit history in place.

RBAC uses least privilege with separated roles such as Viewer, Operator, Supervisor/Approver, System Admin and Auditor.

## Implementation phases

1. Shadow correlation core: durable schema, immutable report identity, pairwise deterministic scoring, negative evidence, cluster/membership revisions, explainability.
2. Durable async jobs, idempotency/retry, merge/split/reopen, concurrency controls.
3. Planned-outage lane, freshness/unavailable semantics.
4. Operator review/labels/manual override/RBAC/tamper-evident audit.
5. Correlation API + transactional outbox/webhook/DLQ for n8n.
6. Root-cause hypotheses, recurrence/equipment issue thread, maintenance review candidates.
7. Shadow evaluation, calibration, side-by-side version comparison, canary and controlled rollout.

No phase may change current customer-facing n8n v1 behavior unless an explicit later capability/version gate is approved.


## Phase 2 implementation status — durable async worker

Implemented on feature branch only; not enabled in production by this change.

Runtime feature flag:
- `INCIDENT_CORRELATION_MODE=off|shadow` (default `off`)
- `INCIDENT_CORRELATION_MAX_ATTEMPTS` (default 5)
- `INCIDENT_CORRELATION_POLL_MS` (default 1000)
- `INCIDENT_CORRELATION_LEASE_SECONDS` (default 30)
- `INCIDENT_CORRELATION_SNAPSHOT_LIMIT` (default 1000; computational bound, not a temporal eligibility cutoff)

Accepted chatbot reports are captured into a privacy-safe correlation record/evidence revision and durable PostgreSQL job. `NEEDS_MORE_INFO` reports do not enter correlation. The queue write occurs only after the authoritative Core report has been durably accepted; correlation computation is asynchronous and its failure never changes the legacy chatbot ACK semantics. The queue capture is attempted before the HTTP ACK is serialized to minimize the process-crash gap, but capture failure remains non-gating and is recorded only as a safe operational warning.

Job lifecycle is durable: `PENDING -> PROCESSING -> RETRYING -> SUCCEEDED/FAILED`. Workers claim with `FOR UPDATE SKIP LOCKED`, bounded attempts, exponential backoff and a lease. An expired `PROCESSING` lease can be reclaimed after process loss. Job payload contains report/evidence references only, never customer name/phone/raw chat/API secrets.

Concurrency uses an ordered set of scoped PostgreSQL advisory locks derived from feeder, upstream protection, transformer and the administrative fallback scope. Related jobs therefore share at least one deterministic lock even when evidence completeness differs, without taking a whole-system lock. Candidate retrieval is topology-first; known unrelated electrical scopes do not re-enter through administrative similarity. Common upstream protection can keep cross-feeder reports in the same candidate scope. Cluster revisions additionally use optimistic `expected_revision`; stale writers return a revision conflict and are retried from current state. No whole-system correlation lock is used.

Phase 2 persists pairwise relationship revisions, suspected-cluster revisions, versioned report membership and merge/split lineage. It remains Shadow-only: no Operational Incident, Work Order, root-cause confirmation, n8n correlation action, or customer-facing message is created by this worker.


## Phase 5 slice status — n8n authoritative read interface

Implementation branch: `feat/incident-correlation-n8n-read-v1-20260826` (child of Phase-2 branch).

This slice adds a read-only safe correlation endpoint:

`GET /api/v1/chatbot-reports/{ticket_id}/correlation`

Key constraints:
- legacy chatbot ACK/status semantics remain unchanged;
- endpoint uses the existing dedicated outage-integration authentication boundary;
- n8n receives backend-decided safe state/confidence level only, not numeric score or topology scoring details;
- raw internal cluster ID is replaced by a one-way safe `cluster_ref`;
- `bot_action=NO_CUSTOMER_ACTION`, `customer_truth_changed=false`, `mode=shadow`, and `production_send=blocked` remain enforced;
- async worker `PENDING/PROCESSING/RETRYING` maps to safe `PENDING`;
- completed singleton maps to `NO_CLUSTER`;
- active cluster maps to `SUSPECTED_RELATED` (or future backend-owned `MULTIPLE_CLUSTER_CANDIDATES`);
- permanent processing failure/capability gap maps to `UNAVAILABLE` and never rewrites the accepted outage receipt;
- planned-outage authoritative match remains a separate lane and may surface as `PLANNED_OUTAGE_LINKED`.

Detailed n8n contract: `docs/integrations/INCIDENT_CORRELATION_N8N_READ_V1.md`.

This is the GET/recovery slice of Phase 5 only. Transactional outbox/webhook/DLQ push remains a later slice.
