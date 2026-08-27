# PEA Intellisense — Incident Correlation Shadow Calibration v1

Updated: 2026-08-26 Asia/Bangkok
Status: SHADOW EVALUATION HARNESS — NO THRESHOLD PROMOTION AUTHORIZED

## Purpose

This harness evaluates the deterministic scores already produced by the Go Incident Correlation Shadow engine against human-reviewed pair labels. It is precision-first and is designed to quantify false-merge risk before any runtime threshold change.

It deliberately does **not** reimplement the Go scoring formula in Python. Runtime scoring remains authoritative in `apps/api-go/internal/correlation/engine.go`.

## Non-negotiable safety rules

- `mode=shadow` remains mandatory.
- `production_send=blocked` remains mandatory.
- Correlation does not confirm an outage, Operational Incident, equipment failure, or root cause.
- Do not promote a threshold automatically from this report.
- Do not treat a perfect observed precision on a small sample as certainty; Wilson lower confidence bounds are reported.
- Do not include customer name, phone, raw chat text, meter IDs, API secrets, tokens, or private GIS/service credentials in score or label files.
- Mixed engine versions must be evaluated separately.

## Why score data and labels are separate

Calibration uses two independent JSONL inputs.

1. **Immutable runtime score export** — generated from persisted Go-engine relationship decisions.
2. **Human review label file** — contains only the reviewer decision metadata and cannot contain confidence score, decision hash, raw evidence, or customer fields.

The harness joins both files using `pair_ref`. This prevents an operator from silently changing the engine score while entering the ground-truth label.

## Runtime score schema

Schema: `incident-correlation-score-export.v1`

Each line must contain only:

```json
{
  "schema_version": "incident-correlation-score-export.v1",
  "pair_ref": "pair_<opaque-ref>",
  "engine_version": "incident-correlation-shadow-v1.0.0",
  "decision_hash": "<lowercase-hex-hash>",
  "confidence_score": 0.0,
  "hard_veto": false,
  "eligible_for_unplanned": true,
  "flags": []
}
```

The score export is intended to be generated from the persisted latest relationship revision. It must not be hand-edited for calibration.

## Human review label schema

Schema: `incident-correlation-review-label.v1`

Each line must contain only:

```json
{
  "schema_version": "incident-correlation-review-label.v1",
  "pair_ref": "pair_<opaque-ref>",
  "review_case_ref": "case_<opaque-ref>",
  "label": "SAME_INCIDENT",
  "risk_tier": "HIGH",
  "split": "CALIBRATION"
}
```

Allowed labels:

- `SAME_INCIDENT`
- `DIFFERENT_INCIDENT`
- `INSUFFICIENT_EVIDENCE`

Allowed risk tiers:

- `NORMAL`
- `HIGH`
- `CRITICAL`

Allowed splits:

- `CALIBRATION`
- `EVALUATION`
- `UNSPECIFIED`

`review_case_ref` must group relationships belonging to the same underlying review case. The harness rejects a case that appears in both CALIBRATION and EVALUATION, preventing case-level leakage.

The split must be assigned deliberately before final metric review. Do not move difficult cases between splits after seeing threshold results.

## Read-only score export from PostgreSQL

The following query emits privacy-safe JSONL-ready rows from the latest persisted relationship revision. Run it only through an approved read-only database path. Do not place database credentials in scripts, Git, screenshots, handoff files, or ChatGPT.

```sql
WITH latest AS (
    SELECT DISTINCT ON (report_a_id, report_b_id)
        report_a_id,
        report_b_id,
        decision_hash,
        confidence_score,
        hard_veto,
        evidence_json,
        engine_version,
        revision
    FROM correlation_report_relationships
    ORDER BY report_a_id, report_b_id, revision DESC
)
SELECT json_build_object(
    'schema_version', 'incident-correlation-score-export.v1',
    'pair_ref', 'pair_' || substr(decision_hash, 1, 24),
    'engine_version', engine_version,
    'decision_hash', decision_hash,
    'confidence_score', confidence_score,
    'hard_veto', hard_veto,
    'eligible_for_unplanned', COALESCE((evidence_json->>'eligible_for_unplanned')::boolean, false),
    'flags', COALESCE(evidence_json->'flags', '[]'::jsonb)
)::text
FROM latest
ORDER BY decision_hash;
```

This query intentionally omits report IDs, ticket IDs, channel/session identifiers, location text, customer fields, raw evidence and topology details. A separate controlled internal reviewer surface may show the minimum evidence necessary for a human label, but that reviewer surface is not a calibration input file.

## Running the harness

```text
python -m shared_core.incident_correlation.calibration ^
  --scores path\to\runtime_scores.jsonl ^
  --labels path\to\review_labels.jsonl ^
  --output-dir runtime\incident-correlation-calibration\run_xxx ^
  --step 1
```

Outputs:

- `incident_correlation_calibration_summary.json`
- `incident_correlation_calibration_report.md`
- `incident_correlation_threshold_sweep_all.csv`
- calibration/evaluation sweep CSVs when those splits exist
- `incident_correlation_pareto_frontier.csv`

## Metrics

For each threshold the harness reports:

- TP / FP / TN / FN
- precision
- 95% Wilson lower bound for precision
- recall
- 95% Wilson lower bound for recall
- F1
- specificity
- `false_merge_count`
- `false_split_count`
- `false_merge_high_critical`
- `hard_safety_pass`
- `zero_false_merge_pass`

A positive prediction means:

```text
eligible_for_unplanned
AND NOT hard_veto
AND confidence_score >= threshold
```

`INSUFFICIENT_EVIDENCE` rows are counted in review coverage but excluded from binary performance metrics.

## Safety interpretation

The existing Shadow design requires zero known false merges in reviewed HIGH/CRITICAL cases. The harness therefore marks a threshold `hard_safety_pass` only when `false_merge_high_critical == 0` on the evaluated split.

This is a safety floor, not sufficient evidence for promotion. Sample size, uncertainty bounds, class balance, operational consequences and held-out evaluation results must still be reviewed.

## No automatic promotion

The harness lists Pareto and zero-false-merge candidates but never writes a new runtime threshold and never changes `DefaultShadowConfig()`.

A threshold change requires a separate reviewed decision with:

1. exact engine version;
2. immutable score-export hash;
3. label-file hash;
4. calibration/evaluation counts;
5. false-merge evidence, especially HIGH/CRITICAL cases;
6. uncertainty bounds;
7. Shadow-only rollout plan;
8. rollback threshold/config;
9. explicit approval before code/config change.

## Weight and time-decay calibration — later phase

v1 calibrates decision thresholds against scores already produced by the authoritative Go engine. It does not search feature weights or time decay.

Weight/time-decay tuning requires an additional parity gate so candidate scoring cannot diverge from Go runtime semantics. Before that phase, create golden vectors directly from the Go scorer and verify any offline candidate evaluator against those vectors exactly. Do not optimize weights by copying the scorer into another language without parity evidence.

## Current data status

The harness is code-complete for reviewed score/label inputs, but there is currently no claim that a representative reviewed Incident Correlation Shadow dataset exists. Until real reviewed Shadow relationships are exported and labeled, no threshold recommendation is valid.

## Provenance and cluster-level limitation

CLI-generated summaries include SHA-256 for both score and label inputs. Preserve those hashes with any threshold-review decision so the result can be reproduced from the exact reviewed dataset.

v1 is a **pairwise decision-threshold** evaluator. This matches the safety-critical edge used by complete-link clustering, but it is not sufficient by itself to validate dynamic cluster behavior. Before any runtime threshold promotion, replay full multi-report sequences and verify cluster-level outcomes including rolling arrivals, false merge, false split, merge, split, reopen, planned-outage separation, stale topology, and late evidence revision. The existing n8n/Incident Correlation acceptance matrix should be used as the scenario floor for that replay.
