# Incident Correlation Cluster Replay / Evaluation v1

Status: Shadow evaluation only

This layer evaluates the **runtime cluster projection as a sequence of reviewed steps**. It does not reimplement the Go scorer or clustering worker and it does not change any runtime threshold.

## Why this exists

Pairwise threshold calibration is necessary but insufficient. A production correlation system can still fail at the cluster level through:

- false merge: two real incidents become one cluster,
- false split: one real incident becomes multiple clusters,
- rolling-arrival instability,
- late-arrival reassignment,
- incorrect MERGE/SPLIT lineage,
- reopening a historical incident incorrectly or failing to reopen when required,
- reports disappearing from evaluation because only multi-report clusters were exported.

Replay v1 measures those failure modes directly.

## Runtime boundary

The authoritative runtime behavior remains the Go Incident Correlation Shadow worker.

The evaluator consumes an immutable export of the **observed runtime projection**. Python never recalculates relationship weights, time decay, candidate scope or complete-link cluster membership.

Current reviewed Phase-2 worker behavior supports deterministic projection, membership revisions, MERGE, SPLIT and lineage persistence. The schema supports `QUIET`, `CLOSED` and `REOPENED`, but the reviewed worker currently does not contain a time-based lifecycle state machine that drives `QUIET/CLOSED/REOPENED`. Consequently, an expected REOPEN scenario is intentionally allowed in reviewed truth and should surface as a measurable gap until that runtime feature exists.

## Two-file model

### 1. Runtime observation JSONL

Schema: `incident-correlation-cluster-observation.v1`

Required fields:

```json
{
  "schema_version": "incident-correlation-cluster-observation.v1",
  "scenario_ref": "scenario_opaque_001",
  "step_index": 0,
  "engine_version": "incident-correlation-shadow-v1.0.0",
  "active_report_refs": ["report_ref_a", "report_ref_b"],
  "observed_partition": [["report_ref_a", "report_ref_b"]],
  "observed_transition": "NEW",
  "observed_lineage_types": []
}
```

Rules:

- `scenario_ref` and report refs are opaque/pseudonymous references only.
- No raw customer message, meter number, PEANO list, customer identity, phone, address, token, credential or internal endpoint is accepted.
- Unknown fields are rejected.
- One engine version per replay run.
- `step_index` must be contiguous from `0` inside each scenario.
- `observed_partition` must partition **all** `active_report_refs` exactly. Reports that do not belong to a multi-report cluster must appear as singleton clusters.
- Raw internal cluster IDs are not required and should not be exported.

Allowed transitions:

`NONE`, `NEW`, `UNCHANGED`, `ADD_SINGLETON`, `EXPAND`, `MERGE`, `SPLIT`, `CLOSE`, `REOPEN`

Allowed lineage types:

`MERGE`, `SPLIT`, `RECURRENCE`, `RELATED`

### 2. Reviewed truth JSONL

Schema: `incident-correlation-cluster-truth.v1`

```json
{
  "schema_version": "incident-correlation-cluster-truth.v1",
  "scenario_ref": "scenario_opaque_001",
  "step_index": 0,
  "review_case_ref": "review_case_opaque_001",
  "active_report_refs": ["report_ref_a", "report_ref_b"],
  "expected_partition": [["report_ref_a", "report_ref_b"]],
  "expected_transition": "NEW",
  "expected_lineage_types": [],
  "risk_tier": "NORMAL",
  "split": "EVALUATION"
}
```

`risk_tier`: `NORMAL`, `HIGH`, `CRITICAL`

`split`: `CALIBRATION`, `EVALUATION`, `UNSPECIFIED`

Every step belonging to the same `review_case_ref` must remain entirely inside one held-out split. The loader rejects case-level calibration/evaluation leakage.

## Metrics

For each replay step, cluster IDs are ignored. The evaluator compares partitions of opaque report refs.

It derives all unordered report pairs that the runtime placed together and all report pairs that reviewed truth says belong together.

Primary safety metrics:

- pair precision,
- pair recall,
- pair F1,
- false-merge pair count,
- false-split pair count,
- High/Critical false-merge step count,
- exact partition match rate,
- transition accuracy,
- lineage accuracy,
- Wilson 95% lower bounds for pair precision/recall,
- hard safety pass (`false_merge_pairs == 0` and no High/Critical false-merge step).

False merge is treated as the more dangerous error because it may collapse unrelated outage reports into one suspected incident. This remains a Shadow metric and is not customer-facing truth.

## Required replay scenarios before any threshold promotion

A representative reviewed set should include at minimum:

1. single report / singleton,
2. same-transformer rolling arrival,
3. same-feeder different-transformer reports,
4. common-upstream cross-feeder reports,
5. authoritative topology conflict,
6. same village but different electrical source,
7. ambiguous/stale topology,
8. planned-outage separate lane,
9. late related report,
10. late unrelated report,
11. duplicate/idempotent retry,
12. MERGE of two previous clusters,
13. SPLIT after evidence revision,
14. closed/quiet incident receiving recurrence evidence,
15. explicit expected REOPEN,
16. cross-channel reports where reporter identity must not be guessed.

Synthetic scenarios are suitable for software correctness tests only. They are not evidence for production threshold selection.

## Running

```text
python -m ais_etr.incident_correlation_cluster_replay \
  --observations runtime/.../observations.jsonl \
  --truth runtime/.../reviewed_truth.jsonl \
  --output-dir runtime/.../cluster-replay-out
```

Outputs:

- `incident_correlation_cluster_replay_summary.json`
- `incident_correlation_cluster_replay_steps.csv`
- `incident_correlation_cluster_replay_report.md`

The summary records SHA-256 of both input files.

## Promotion rule

Replay v1 never promotes a runtime threshold, changes config, confirms an outage, confirms root cause, or changes customer messaging.

Before any future threshold/config promotion:

- pairwise calibration must pass its reviewed-data gate,
- cluster-level held-out replay must show acceptable false-merge safety,
- MERGE/SPLIT behavior must be reviewed,
- lifecycle/reopen expectations must be implemented and replay-tested if the use case requires them,
- n8n Shadow E2E must still preserve `NO_CUSTOMER_ACTION`,
- `mode=shadow` and `production_send=blocked` remain enforced until a separate owner-approved production gate.

## Current result

No representative reviewed cluster replay dataset is currently available in this sanitized branch. Therefore there is **no cluster-level operational score and no threshold recommendation yet**.
