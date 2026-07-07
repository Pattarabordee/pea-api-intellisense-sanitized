CREATE TABLE IF NOT EXISTS ais_truth_ledger (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL UNIQUE REFERENCES ais_inbound_requests(request_id) ON DELETE CASCADE,
    source text NOT NULL DEFAULT 'AIS',
    source_event_id text NOT NULL DEFAULT '',
    site_hash text NOT NULL DEFAULT '',
    site_last4 text NOT NULL DEFAULT '',
    meter_hash text NOT NULL DEFAULT '',
    meter_last4 text NOT NULL DEFAULT '',
    event_type text NOT NULL DEFAULT 'UNKNOWN',
    detected_at timestamptz NOT NULL,
    outage_at timestamptz,
    restore_at timestamptz,
    timestamp_quality jsonb NOT NULL DEFAULT '{}'::jsonb,
    payload_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    validation_status text NOT NULL DEFAULT 'REVIEW_EVENT_TYPE',
    production_send text NOT NULL DEFAULT 'blocked',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ais_truth_ledger_event_type CHECK (event_type IN ('OUTAGE','RESTORE','STATUS','UNKNOWN')),
    CONSTRAINT ais_truth_ledger_validation_status CHECK (validation_status IN ('READY_FOR_LEDGER','REVIEW_EVENT_TYPE','REVIEW_TIMESTAMP','REVIEW_RESTORE_BEFORE_OUTAGE')),
    CONSTRAINT ais_truth_ledger_prod_blocked CHECK (production_send = 'blocked')
);

CREATE INDEX IF NOT EXISTS idx_ais_truth_ledger_event_type_detected
ON ais_truth_ledger (event_type, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_ais_truth_ledger_validation_status
ON ais_truth_ledger (validation_status, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_ais_truth_ledger_meter_detected
ON ais_truth_ledger (meter_hash, detected_at DESC);
