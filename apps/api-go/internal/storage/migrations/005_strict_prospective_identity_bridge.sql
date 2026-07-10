ALTER TABLE ais_truth_intervals
    ADD COLUMN IF NOT EXISTS correlation_hash text NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS bridge_status text NOT NULL DEFAULT 'LEGACY_UNVERIFIED';

UPDATE ais_truth_intervals
SET bridge_status = 'LEGACY_UNVERIFIED'
WHERE bridge_status = '';

ALTER TABLE ais_truth_intervals
    DROP CONSTRAINT IF EXISTS ais_truth_intervals_bridge_status;

ALTER TABLE ais_truth_intervals
    ADD CONSTRAINT ais_truth_intervals_bridge_status CHECK (
        bridge_status IN (
            'LEGACY_UNVERIFIED',
            'STRICT_AWAITING_RESTORE',
            'STRICT_MODEL_READY',
            'STRICT_DURATION_REVIEW',
            'REVIEW_IDENTITY_CONFLICT'
        )
    );

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
            'REVIEW_DURATION_OUT_OF_RANGE'
        )
    );

CREATE INDEX IF NOT EXISTS idx_ais_truth_intervals_strict_open
ON ais_truth_intervals (correlation_hash, meter_hash, site_hash, outage_at DESC)
WHERE pair_status = 'OPEN' AND bridge_status = 'STRICT_AWAITING_RESTORE';

CREATE INDEX IF NOT EXISTS idx_ais_truth_intervals_bridge_status
ON ais_truth_intervals (bridge_status, outage_at DESC);
