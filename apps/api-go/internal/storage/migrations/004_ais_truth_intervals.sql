CREATE TABLE IF NOT EXISTS ais_truth_intervals (
    id bigserial PRIMARY KEY,
    interval_id text NOT NULL UNIQUE,
    source text NOT NULL DEFAULT 'AIS',
    outage_request_id text REFERENCES ais_inbound_requests(request_id) ON DELETE SET NULL,
    restore_request_id text REFERENCES ais_inbound_requests(request_id) ON DELETE SET NULL,
    meter_hash text NOT NULL DEFAULT '',
    meter_last4 text NOT NULL DEFAULT '',
    site_hash text NOT NULL DEFAULT '',
    site_last4 text NOT NULL DEFAULT '',
    outage_at timestamptz NOT NULL,
    restore_at timestamptz,
    duration_minutes numeric,
    pair_status text NOT NULL DEFAULT 'OPEN',
    evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    production_send text NOT NULL DEFAULT 'blocked',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ais_truth_intervals_pair_status CHECK (pair_status IN ('OPEN','CLOSED','REVIEW')),
    CONSTRAINT ais_truth_intervals_duration_nonnegative CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
    CONSTRAINT ais_truth_intervals_prod_blocked CHECK (production_send = 'blocked')
);

CREATE INDEX IF NOT EXISTS idx_ais_truth_intervals_meter_open
ON ais_truth_intervals (meter_hash, pair_status, outage_at DESC);

CREATE INDEX IF NOT EXISTS idx_ais_truth_intervals_site_open
ON ais_truth_intervals (site_hash, pair_status, outage_at DESC);

CREATE INDEX IF NOT EXISTS idx_ais_truth_intervals_status_time
ON ais_truth_intervals (pair_status, outage_at DESC);
