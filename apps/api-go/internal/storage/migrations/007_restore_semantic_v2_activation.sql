ALTER TABLE ais_truth_ledger
    ADD COLUMN IF NOT EXISTS semantic_mapping_version text NOT NULL DEFAULT 'legacy';

ALTER TABLE ais_truth_intervals
    ADD COLUMN IF NOT EXISTS semantic_mapping_version text NOT NULL DEFAULT 'legacy';

UPDATE ais_truth_ledger l
SET semantic_mapping_version = 'capture_v1'
FROM ais_inbound_requests r
WHERE r.request_id = l.request_id
  AND r.request_json ->> 'semantic_capture_version' = 'v1'
  AND l.semantic_mapping_version = 'legacy';

UPDATE ais_truth_intervals i
SET semantic_mapping_version = l.semantic_mapping_version
FROM ais_truth_ledger l
WHERE l.request_id = i.outage_request_id
  AND i.semantic_mapping_version = 'legacy';

ALTER TABLE ais_truth_intervals
    DROP CONSTRAINT IF EXISTS ais_truth_intervals_bridge_status;

ALTER TABLE ais_truth_intervals
    ADD CONSTRAINT ais_truth_intervals_bridge_status CHECK (
        bridge_status IN (
            'LEGACY_UNVERIFIED',
            'STRICT_AWAITING_RESTORE',
            'STRICT_MODEL_READY',
            'STRICT_DURATION_REVIEW',
            'REVIEW_IDENTITY_CONFLICT',
            'METER_STATE_AWAITING_RESTORE',
            'METER_STATE_MODEL_READY',
            'METER_STATE_DURATION_REVIEW',
            'REVIEW_MULTIPLE_OPEN_INTERVALS',
            'REVIEW_PREACTIVATION_PAIR',
            'REVIEW_PREACTIVATION_OPEN',
            'REVIEW_STALE_PREACTIVATION_OPEN'
        )
    );

CREATE TABLE IF NOT EXISTS ais_truth_interval_status_audit (
    id bigserial PRIMARY KEY,
    interval_id text NOT NULL,
    old_pair_status text NOT NULL,
    old_bridge_status text NOT NULL,
    new_pair_status text NOT NULL,
    new_bridge_status text NOT NULL,
    reason text NOT NULL,
    semantic_mapping_version text NOT NULL,
    production_send text NOT NULL DEFAULT 'blocked',
    changed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ais_truth_interval_status_audit_prod_blocked CHECK (production_send = 'blocked'),
    CONSTRAINT ais_truth_interval_status_audit_unique_transition UNIQUE (
        interval_id, new_bridge_status, semantic_mapping_version
    )
);

WITH classified AS (
    SELECT
        i.interval_id,
        i.pair_status AS old_pair_status,
        i.bridge_status AS old_bridge_status,
        i.semantic_mapping_version,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM ais_truth_ledger restore
                WHERE restore.meter_hash = i.meter_hash
                  AND restore.detected_at > i.outage_at
                  AND restore.event_type = 'STATUS'
                  AND restore.event_type_source = 'mapped_unknown'
                  AND restore.semantic_mapping_version = i.semantic_mapping_version
                  AND restore.payload_summary_json #>> '{semantic_signals,alarm_type,value}' = 'AC_MAIN_RESTORE'
            ) THEN 'REVIEW_PREACTIVATION_PAIR'
            WHEN i.outage_at < now() - interval '24 hours' THEN 'REVIEW_STALE_PREACTIVATION_OPEN'
            ELSE 'REVIEW_PREACTIVATION_OPEN'
        END AS new_bridge_status,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM ais_truth_ledger restore
                WHERE restore.meter_hash = i.meter_hash
                  AND restore.detected_at > i.outage_at
                  AND restore.event_type = 'STATUS'
                  AND restore.event_type_source = 'mapped_unknown'
                  AND restore.semantic_mapping_version = i.semantic_mapping_version
                  AND restore.payload_summary_json #>> '{semantic_signals,alarm_type,value}' = 'AC_MAIN_RESTORE'
            ) THEN 'preactivation_restore_candidate_audit_only'
            WHEN i.outage_at < now() - interval '24 hours' THEN 'preactivation_open_stale'
            ELSE 'preactivation_open_not_model_ready'
        END AS reason
    FROM ais_truth_intervals i
    WHERE i.pair_status = 'OPEN'
      AND i.bridge_status = 'METER_STATE_AWAITING_RESTORE'
      AND i.semantic_mapping_version <> 'alarm_mapping_v2'
)
INSERT INTO ais_truth_interval_status_audit (
    interval_id, old_pair_status, old_bridge_status, new_pair_status,
    new_bridge_status, reason, semantic_mapping_version, production_send
)
SELECT interval_id, old_pair_status, old_bridge_status, 'REVIEW',
       new_bridge_status, reason, semantic_mapping_version, 'blocked'
FROM classified
ON CONFLICT (interval_id, new_bridge_status, semantic_mapping_version) DO NOTHING;

WITH classified AS (
    SELECT
        i.id,
        i.semantic_mapping_version,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM ais_truth_ledger restore
                WHERE restore.meter_hash = i.meter_hash
                  AND restore.detected_at > i.outage_at
                  AND restore.event_type = 'STATUS'
                  AND restore.event_type_source = 'mapped_unknown'
                  AND restore.semantic_mapping_version = i.semantic_mapping_version
                  AND restore.payload_summary_json #>> '{semantic_signals,alarm_type,value}' = 'AC_MAIN_RESTORE'
            ) THEN 'REVIEW_PREACTIVATION_PAIR'
            WHEN i.outage_at < now() - interval '24 hours' THEN 'REVIEW_STALE_PREACTIVATION_OPEN'
            ELSE 'REVIEW_PREACTIVATION_OPEN'
        END AS new_bridge_status,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM ais_truth_ledger restore
                WHERE restore.meter_hash = i.meter_hash
                  AND restore.detected_at > i.outage_at
                  AND restore.event_type = 'STATUS'
                  AND restore.event_type_source = 'mapped_unknown'
                  AND restore.semantic_mapping_version = i.semantic_mapping_version
                  AND restore.payload_summary_json #>> '{semantic_signals,alarm_type,value}' = 'AC_MAIN_RESTORE'
            ) THEN 'preactivation_restore_candidate_audit_only'
            WHEN i.outage_at < now() - interval '24 hours' THEN 'preactivation_open_stale'
            ELSE 'preactivation_open_not_model_ready'
        END AS reason
    FROM ais_truth_intervals i
    WHERE i.pair_status = 'OPEN'
      AND i.bridge_status = 'METER_STATE_AWAITING_RESTORE'
      AND i.semantic_mapping_version <> 'alarm_mapping_v2'
)
UPDATE ais_truth_intervals i
SET pair_status = 'REVIEW',
    bridge_status = classified.new_bridge_status,
    evidence_json = jsonb_build_object(
        'source', 'migration_007_restore_semantic_v2_activation',
        'reason', classified.reason,
        'semantic_mapping_version', classified.semantic_mapping_version,
        'use_for_training', false,
        'use_for_evaluation', false,
        'production_send', 'blocked'
    ),
    updated_at = now()
FROM classified
WHERE i.id = classified.id;

CREATE INDEX IF NOT EXISTS idx_ais_truth_ledger_semantic_mapping_version
ON ais_truth_ledger (semantic_mapping_version, event_type, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_ais_truth_intervals_semantic_mapping_version
ON ais_truth_intervals (semantic_mapping_version, pair_status, outage_at DESC);
