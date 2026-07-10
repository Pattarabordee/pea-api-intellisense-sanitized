ALTER TABLE ais_truth_ledger
    ADD COLUMN IF NOT EXISTS source_event_hash text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS event_type_source text NOT NULL DEFAULT 'legacy';

ALTER TABLE ais_truth_ledger
    DROP CONSTRAINT IF EXISTS ais_truth_ledger_validation_status;

ALTER TABLE ais_truth_ledger
    ADD CONSTRAINT ais_truth_ledger_validation_status CHECK (
        validation_status IN (
            'READY_FOR_LEDGER',
            'REVIEW_EVENT_TYPE',
            'REVIEW_TIMESTAMP',
            'REVIEW_RESTORE_BEFORE_OUTAGE',
            'REVIEW_IDENTITY_KEY_REQUIRED',
            'REVIEW_OUTAGE_TIMESTAMP',
            'REVIEW_RESTORE_TIMESTAMP',
            'REVIEW_NO_MATCHING_OPEN_INTERVAL',
            'REVIEW_IDENTITY_CONFLICT',
            'REVIEW_DURATION_OUT_OF_RANGE',
            'REVIEW_METER_REQUIRED',
            'REVIEW_NO_OPEN_INTERVAL',
            'REVIEW_MULTIPLE_OPEN_INTERVALS'
        )
    );

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
            'REVIEW_MULTIPLE_OPEN_INTERVALS'
        )
    );

WITH conflicting AS (
    SELECT meter_hash
    FROM ais_truth_intervals
    WHERE pair_status = 'OPEN'
    GROUP BY meter_hash
    HAVING count(*) > 1
)
UPDATE ais_truth_intervals i
SET pair_status = 'REVIEW',
    bridge_status = 'REVIEW_MULTIPLE_OPEN_INTERVALS',
    evidence_json = jsonb_build_object(
        'source', 'migration_006_meter_state_truth_capture',
        'reason', 'preexisting_multiple_open_intervals',
        'production_send', 'blocked'
    ),
    updated_at = now()
FROM conflicting c
WHERE i.meter_hash = c.meter_hash AND i.pair_status = 'OPEN';

CREATE UNIQUE INDEX IF NOT EXISTS idx_ais_truth_intervals_one_meter_state_open
ON ais_truth_intervals (meter_hash)
WHERE pair_status = 'OPEN' AND bridge_status = 'METER_STATE_AWAITING_RESTORE';

CREATE INDEX IF NOT EXISTS idx_ais_truth_ledger_source_event_hash
ON ais_truth_ledger (source_event_hash)
WHERE source_event_hash <> '';
