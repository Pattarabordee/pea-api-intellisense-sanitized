CREATE TABLE IF NOT EXISTS send_policy_snapshots (
    id bigserial PRIMARY KEY,
    mode text NOT NULL DEFAULT 'blocked',
    emergency_off boolean NOT NULL DEFAULT false,
    callback_transport text NOT NULL DEFAULT 'dry_run',
    gate_version text NOT NULL DEFAULT 'blocked_green_gate',
    source text NOT NULL DEFAULT 'api',
    reason text NOT NULL DEFAULT '',
    production_send text NOT NULL DEFAULT 'blocked',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT send_policy_mode CHECK (mode IN ('blocked','human_review_only','status_only_green_lane','auto_green_lane','emergency_off')),
    CONSTRAINT send_policy_transport CHECK (callback_transport IN ('dry_run','real')),
    CONSTRAINT send_policy_prod_blocked CHECK (production_send = 'blocked')
);

CREATE TABLE IF NOT EXISTS send_decisions (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL REFERENCES ais_inbound_requests(request_id) ON DELETE CASCADE,
    policy_mode text NOT NULL DEFAULT 'blocked',
    effective_mode text NOT NULL DEFAULT 'blocked',
    eligibility_status text NOT NULL DEFAULT 'red_blocked',
    decision text NOT NULL DEFAULT 'blocked',
    reason text NOT NULL DEFAULT '',
    gate_version text NOT NULL DEFAULT 'blocked_green_gate',
    source text NOT NULL DEFAULT 'api',
    operator_actor text NOT NULL DEFAULT '',
    production_send text NOT NULL DEFAULT 'blocked',
    decided_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT send_decisions_policy_mode CHECK (policy_mode IN ('blocked','human_review_only','status_only_green_lane','auto_green_lane','emergency_off')),
    CONSTRAINT send_decisions_effective_mode CHECK (effective_mode IN ('blocked','human_review_only','status_only_green_lane','auto_green_lane','emergency_off')),
    CONSTRAINT send_decisions_decision CHECK (decision IN ('blocked','human_review_required','status_only_dry_run','auto_green_dry_run','emergency_off')),
    CONSTRAINT send_decisions_prod_blocked CHECK (production_send = 'blocked')
);

CREATE INDEX IF NOT EXISTS idx_send_decisions_request_id_id
ON send_decisions (request_id, id DESC);

CREATE TABLE IF NOT EXISTS callback_outbox (
    id bigserial PRIMARY KEY,
    request_id text NOT NULL REFERENCES ais_inbound_requests(request_id) ON DELETE CASCADE,
    decision_id bigint REFERENCES send_decisions(id) ON DELETE SET NULL,
    payload_hash text NOT NULL,
    payload_json jsonb NOT NULL,
    transport text NOT NULL DEFAULT 'dry_run',
    status text NOT NULL DEFAULT 'DRY_RUN_HELD',
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    next_attempt_at timestamptz,
    last_error text NOT NULL DEFAULT '',
    production_send text NOT NULL DEFAULT 'blocked',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT callback_outbox_transport CHECK (transport IN ('dry_run','real')),
    CONSTRAINT callback_outbox_status CHECK (status IN ('DRY_RUN_HELD','PENDING','RETRY_WAIT','SENT','DEAD_LETTER','BLOCKED')),
    CONSTRAINT callback_outbox_attempts CHECK (attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10),
    CONSTRAINT callback_outbox_prod_blocked CHECK (production_send = 'blocked'),
    CONSTRAINT callback_outbox_unique_payload UNIQUE (request_id, payload_hash)
);

CREATE INDEX IF NOT EXISTS idx_callback_outbox_request_id_id
ON callback_outbox (request_id, id DESC);

CREATE TABLE IF NOT EXISTS callback_dead_letters (
    id bigserial PRIMARY KEY,
    outbox_id bigint NOT NULL REFERENCES callback_outbox(id) ON DELETE CASCADE,
    request_id text NOT NULL REFERENCES ais_inbound_requests(request_id) ON DELETE CASCADE,
    final_status text NOT NULL,
    error_class text NOT NULL DEFAULT '',
    last_error text NOT NULL DEFAULT '',
    payload_hash text NOT NULL,
    production_send text NOT NULL DEFAULT 'blocked',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT callback_dead_letters_prod_blocked CHECK (production_send = 'blocked')
);

CREATE INDEX IF NOT EXISTS idx_callback_dead_letters_request_id_created
ON callback_dead_letters (request_id, created_at DESC);
