# PEA Intellisense — Incident Correlation Human Review Queue v1

Updated: 2026-08-27 Asia/Bangkok
Status: SHADOW REVIEW TOOLING — NO THRESHOLD PROMOTION AUTHORIZED

## Purpose

This tool creates a blind human-review queue for Incident Correlation relationship pairs. It is intended to produce labels that can later be joined to the immutable runtime score export by `pair_ref` and evaluated with `incident_correlation_calibration.py`.

The reviewer must not see the model score, confidence level, relationship decision, threshold, raw customer data, raw message text, ticket ID, raw report ID, or raw electrical asset ID while labeling.

## Label semantics

Allowed labels:

- `SAME_INCIDENT` — evidence is sufficient to review the two reports as the same underlying occurrence.
- `DIFFERENT_INCIDENT` — evidence is sufficient to review the reports as distinct underlying occurrences.
- `INSUFFICIENT_EVIDENCE` — available evidence does not justify either conclusion.

Allowed false-merge risk tiers:

- `NORMAL`
- `HIGH`
- `CRITICAL`

The output label JSONL contains exactly:

```json
{
  "schema_version": "incident-correlation-review-label.v1",
  "pair_ref": "pair_<opaque-ref>",
  "review_case_ref": "case_<opaque-ref>",
  "label": "INSUFFICIENT_EVIDENCE",
  "risk_tier": "HIGH",
  "split": "EVALUATION"
}
```

## Candidate schema

Input schema: `incident-correlation-review-candidate.v1`

```json
{
  "schema_version": "incident-correlation-review-candidate.v1",
  "pair_ref": "pair_<opaque-ref>",
  "report_ref_a": "report_<opaque-ref>",
  "report_ref_b": "report_<opaque-ref>",
  "engine_version": "incident-correlation-shadow-v1.0.0",
  "evidence": {
    "temporal_delta_minutes": 3,
    "channel_relation": "DIFFERENT_CHANNEL",
    "admin_relation": "SAME_VILLAGE",
    "feeder_relation": "SAME_FEEDER",
    "transformer_relation": "SAME_TRANSFORMER",
    "upstream_relation": "DIFFERENT_OR_UNKNOWN",
    "topology_freshness_relation": "BOTH_NOT_FRESH",
    "topology_authoritative_relation": "BOTH_AUTHORITATIVE",
    "planned_outage_relation": "BOTH_UNPLANNED_OR_NOT_CHECKED"
  }
}
```

No extra candidate fields are accepted. This intentionally makes it difficult to leak numeric model decisions, customer fields or free-text evidence into the reviewer surface.

## Case grouping and split leakage guard

Two explicit split strategies are supported. The default remains `connected-component-v1` for backward compatibility.

### `connected-component-v1`

The builder computes connected components over opaque `report_ref_a` / `report_ref_b`. All pair relationships connected through a shared report receive the same `review_case_ref`. A deterministic SHA-256 split assignment then places each entire case into either `CALIBRATION` or `EVALUATION`. This is conservative, but a dense relationship graph can collapse a whole cohort into one case and leave no held-out split.

### `report-disjoint-v1`

For dense runtime relationship exports, prefer `report-disjoint-v1`. Each opaque report ref is assigned deterministically to `CALIBRATION` or `EVALUATION` before pair review. A pair is retained only when both endpoint reports are assigned to the same split. Cross-split pairs are dropped and counted in the manifest. Connected components are then computed only inside the retained split-local graph.

This guarantees that the same report cannot appear in both calibration and evaluation while avoiding the all-or-nothing behavior of a single dense connected component. The dropped-pair rule depends only on opaque report refs, the fixed split seed and calibration fraction; it does not inspect model score, confidence, relationship decision or reviewer label.

The manifest records `split_strategy`, `candidate_input_count`, `candidate_count`, `dropped_cross_split_pair_count`, `report_count`, `review_report_count`, `report_split_counts` and `report_leakage_guard`. The browser reviewer cannot edit the split.

Default calibration fraction is 0.70. The split seed and fraction are recorded in the manifest.

## Read-only PostgreSQL candidate export

Run this only through an approved read-only staging/Shadow database path. The query intentionally excludes score, confidence level, relationship state, hard veto, raw ticket/report IDs, raw location values, raw customer data and raw asset IDs.

```sql
WITH latest_relationship AS (
    SELECT DISTINCT ON (report_a_id, report_b_id)
        report_a_id,
        report_b_id,
        decision_hash,
        engine_version
    FROM correlation_report_relationships
    ORDER BY report_a_id, report_b_id, revision DESC
),
latest_evidence AS (
    SELECT DISTINCT ON (report_id)
        report_id,
        topology_json,
        location_json,
        freshness_json,
        planned_outage_state
    FROM correlation_report_evidence_revisions
    ORDER BY report_id, revision DESC
)
SELECT json_build_object(
    'schema_version', 'incident-correlation-review-candidate.v1',
    'pair_ref', 'pair_' || substr(lr.decision_hash, 1, 24),
    'report_ref_a', 'report_' || substr(md5(lr.report_a_id), 1, 24),
    'report_ref_b', 'report_' || substr(md5(lr.report_b_id), 1, 24),
    'engine_version', lr.engine_version,
    'evidence', json_build_object(
        'temporal_delta_minutes', round(abs(extract(epoch FROM (ra.occurred_at - rb.occurred_at))) / 60.0),
        'channel_relation', CASE
            WHEN ra.source_channel = '' OR rb.source_channel = '' THEN 'UNKNOWN'
            WHEN lower(ra.source_channel) = lower(rb.source_channel) THEN 'SAME_CHANNEL'
            ELSE 'DIFFERENT_CHANNEL'
        END,
        'admin_relation', CASE
            WHEN COALESCE(ea.location_json->>'village','') <> ''
             AND COALESCE(eb.location_json->>'village','') <> ''
             AND lower(ea.location_json->>'village') = lower(eb.location_json->>'village')
                THEN 'SAME_VILLAGE'
            WHEN COALESCE(ea.location_json->>'village','') <> ''
             AND COALESCE(eb.location_json->>'village','') <> ''
             AND lower(ea.location_json->>'village') <> lower(eb.location_json->>'village')
             AND COALESCE(ea.location_json->>'subdistrict','') <> ''
             AND lower(ea.location_json->>'subdistrict') = lower(eb.location_json->>'subdistrict')
                THEN 'DIFFERENT_VILLAGE_SAME_SUBDISTRICT'
            WHEN COALESCE(ea.location_json->>'subdistrict','') <> ''
             AND lower(ea.location_json->>'subdistrict') = lower(eb.location_json->>'subdistrict')
                THEN 'SAME_SUBDISTRICT'
            WHEN COALESCE(ea.location_json->>'district','') <> ''
             AND lower(ea.location_json->>'district') = lower(eb.location_json->>'district')
                THEN 'SAME_DISTRICT'
            WHEN COALESCE(ea.location_json->>'province','') <> ''
             AND COALESCE(eb.location_json->>'province','') <> ''
             AND lower(ea.location_json->>'province') <> lower(eb.location_json->>'province')
                THEN 'DIFFERENT_PROVINCE'
            WHEN COALESCE(ea.location_json->>'province','') <> ''
             AND lower(ea.location_json->>'province') = lower(eb.location_json->>'province')
                THEN 'SAME_PROVINCE'
            ELSE 'UNKNOWN'
        END,
        'feeder_relation', CASE
            WHEN COALESCE(ea.topology_json->>'feeder_id','') = ''
              OR COALESCE(eb.topology_json->>'feeder_id','') = ''
                THEN 'ONE_OR_BOTH_UNKNOWN'
            WHEN upper(ea.topology_json->>'feeder_id') = upper(eb.topology_json->>'feeder_id')
                THEN 'SAME_FEEDER'
            ELSE 'DIFFERENT_FEEDER'
        END,
        'transformer_relation', CASE
            WHEN jsonb_array_length(COALESCE(ea.topology_json->'transformer_ids','[]'::jsonb)) = 0
              OR jsonb_array_length(COALESCE(eb.topology_json->'transformer_ids','[]'::jsonb)) = 0
                THEN 'ONE_OR_BOTH_UNKNOWN'
            WHEN EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(COALESCE(ea.topology_json->'transformer_ids','[]'::jsonb)) a(value)
                JOIN jsonb_array_elements_text(COALESCE(eb.topology_json->'transformer_ids','[]'::jsonb)) b(value)
                  ON upper(a.value) = upper(b.value)
            ) THEN 'SAME_TRANSFORMER'
            ELSE 'DIFFERENT_TRANSFORMER'
        END,
        'upstream_relation', CASE
            WHEN EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(COALESCE(ea.topology_json->'upstream_protection_ids','[]'::jsonb)) a(value)
                JOIN jsonb_array_elements_text(COALESCE(eb.topology_json->'upstream_protection_ids','[]'::jsonb)) b(value)
                  ON upper(a.value) = upper(b.value)
            ) THEN 'SHARED_UPSTREAM'
            ELSE 'DIFFERENT_OR_UNKNOWN'
        END,
        'topology_freshness_relation', CASE
            WHEN upper(COALESCE(ea.freshness_json->>'topology','')) = 'FRESH'
             AND upper(COALESCE(eb.freshness_json->>'topology','')) = 'FRESH'
                THEN 'BOTH_FRESH'
            WHEN COALESCE(ea.freshness_json->>'topology','') <> ''
             AND COALESCE(eb.freshness_json->>'topology','') <> ''
             AND upper(ea.freshness_json->>'topology') <> 'FRESH'
             AND upper(eb.freshness_json->>'topology') <> 'FRESH'
                THEN 'BOTH_NOT_FRESH'
            ELSE 'MIXED_OR_UNKNOWN'
        END,
        'topology_authoritative_relation', CASE
            WHEN COALESCE((ea.topology_json->>'authoritative')::boolean, false)
             AND COALESCE((eb.topology_json->>'authoritative')::boolean, false)
                THEN 'BOTH_AUTHORITATIVE'
            ELSE 'NOT_BOTH_AUTHORITATIVE'
        END,
        'planned_outage_relation', CASE
            WHEN upper(ea.planned_outage_state) = 'MATCHED'
              OR upper(eb.planned_outage_state) = 'MATCHED'
                THEN 'ONE_OR_BOTH_MATCHED'
            WHEN upper(ea.planned_outage_state) IN ('AMBIGUOUS','UNAVAILABLE','INCONCLUSIVE')
              OR upper(eb.planned_outage_state) IN ('AMBIGUOUS','UNAVAILABLE','INCONCLUSIVE')
                THEN 'UNCERTAIN'
            ELSE 'BOTH_UNPLANNED_OR_NOT_CHECKED'
        END
    )
)::text
FROM latest_relationship lr
JOIN correlation_reports ra ON ra.report_id = lr.report_a_id
JOIN correlation_reports rb ON rb.report_id = lr.report_b_id
JOIN latest_evidence ea ON ea.report_id = lr.report_a_id
JOIN latest_evidence eb ON eb.report_id = lr.report_b_id
ORDER BY lr.decision_hash;
```

The query uses raw identifiers only inside PostgreSQL to construct opaque references and relation categories. Those raw values are not emitted.

## Build the static queue

```text
python -m ais_etr.incident_correlation_review_queue build ^
  --candidates runtime\review\candidates.jsonl ^
  --output-dir runtime\review\queue_v1 ^
  --split-seed incident-correlation-review-v1 ^
  --calibration-fraction 0.70 ^
  --split-strategy report-disjoint-v1
```

Outputs:

- `incident_correlation_review_queue.html`
- `incident_correlation_review_queue_manifest.json`

The HTML stores review choices only in browser `localStorage` until the reviewer explicitly exports labels.

## Validate exported labels

```text
python -m ais_etr.incident_correlation_review_queue validate-labels ^
  --labels runtime\review\incident_correlation_review_labels.jsonl ^
  --manifest runtime\review\queue_v1\incident_correlation_review_queue_manifest.json
```

Validation checks:

- strict six-field label schema;
- one label per `pair_ref`;
- case-level split consistency;
- pair/case/split assignment matches the queue manifest;
- full queue coverage unless `--allow-partial` is explicitly used.

## Safety interpretation

A completed reviewer queue is not enough to change a runtime threshold. Threshold review still requires:

1. immutable runtime score export from the same engine version;
2. reviewed labels from this blind-review process;
3. calibration/evaluation split integrity;
4. pairwise safety metrics and uncertainty bounds;
5. held-out cluster replay;
6. explicit owner approval before any config/code change.

Synthetic campaign cases may be used to test this reviewer tooling, but synthetic labels must not be presented as operational calibration evidence.
