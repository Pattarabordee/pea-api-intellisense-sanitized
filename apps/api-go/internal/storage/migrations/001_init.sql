CREATE TABLE IF NOT EXISTS ais_inbound_requests (
    request_id text PRIMARY KEY,
    received_at timestamptz NOT NULL DEFAULT now(),
    meter_hash text,
    meter_last4 text,
    detected_at timestamptz NOT NULL,
    detected_at_original text NOT NULL,
    timestamp_quality jsonb NOT NULL DEFAULT '{}'::jsonb,
    province text NOT NULL DEFAULT '',
    district text NOT NULL DEFAULT '',
    subdistrict text NOT NULL DEFAULT '',
    request_json jsonb NOT NULL,
    response_json jsonb NOT NULL,
    callback_status text NOT NULL,
    mode text NOT NULL DEFAULT 'shadow',
    production_send text NOT NULL DEFAULT 'blocked',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ais_inbound_requests_shadow_mode CHECK (mode = 'shadow'),
    CONSTRAINT ais_inbound_requests_prod_blocked CHECK (production_send = 'blocked')
);

CREATE TABLE IF NOT EXISTS ais_inbound_callbacks (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL REFERENCES ais_inbound_requests(request_id) ON DELETE CASCADE,
    callback_url text,
    mode text NOT NULL DEFAULT 'shadow',
    payload_json jsonb NOT NULL,
    status text NOT NULL,
    status_code integer,
    response_text text,
    sent_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ais_inbound_callbacks_shadow_mode CHECK (mode = 'shadow')
);

CREATE INDEX IF NOT EXISTS idx_ais_inbound_callbacks_request_id_id
ON ais_inbound_callbacks (request_id, id DESC);

CREATE TABLE IF NOT EXISTS evidence_traces (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL REFERENCES ais_inbound_requests(request_id) ON DELETE CASCADE,
    trace_status text NOT NULL,
    match_found boolean NOT NULL DEFAULT false,
    match_level text NOT NULL DEFAULT '',
    confidence text NOT NULL DEFAULT 'LOW',
    evidence_json jsonb NOT NULL,
    production_send text NOT NULL DEFAULT 'blocked',
    generated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT evidence_traces_prod_blocked CHECK (production_send = 'blocked')
);

CREATE INDEX IF NOT EXISTS idx_evidence_traces_request_id_id
ON evidence_traces (request_id, id DESC);

CREATE TABLE IF NOT EXISTS etr_candidates (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL REFERENCES ais_inbound_requests(request_id) ON DELETE CASCADE,
    status text NOT NULL,
    p50_minutes numeric,
    q10_minutes numeric,
    q90_minutes numeric,
    risk_level text NOT NULL DEFAULT '',
    model_version text NOT NULL DEFAULT 'shadow',
    production_gate text NOT NULL DEFAULT 'blocked_green_gate',
    production_send text NOT NULL DEFAULT 'blocked',
    generated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT etr_candidates_prod_blocked CHECK (production_send = 'blocked')
);

CREATE INDEX IF NOT EXISTS idx_etr_candidates_request_id_id
ON etr_candidates (request_id, id DESC);

CREATE TABLE IF NOT EXISTS operator_decisions (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL REFERENCES ais_inbound_requests(request_id) ON DELETE CASCADE,
    decision text NOT NULL,
    actor text NOT NULL DEFAULT '',
    notes text NOT NULL DEFAULT '',
    production_send text NOT NULL DEFAULT 'blocked',
    decided_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT operator_decisions_prod_blocked CHECK (production_send = 'blocked')
);

CREATE TABLE IF NOT EXISTS audit_events (
    id bigserial PRIMARY KEY,
    event_type text NOT NULL,
    request_id text,
    details_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_request_id_created
ON audit_events (request_id, created_at DESC);
