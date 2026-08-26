CREATE TABLE IF NOT EXISTS planned_outage_decisions (
    id bigserial PRIMARY KEY,
    ticket_id text NOT NULL,
    revision integer NOT NULL,
    decision_hash text NOT NULL UNIQUE,
    recorded_at timestamptz NOT NULL,
    occurred_at timestamptz NOT NULL,
    session_ref_hash text NOT NULL DEFAULT '',
    province text NOT NULL DEFAULT '',
    district text NOT NULL DEFAULT '',
    subdistrict text NOT NULL DEFAULT '',
    location_text text NOT NULL DEFAULT '',
    decision text NOT NULL,
    source_mode text NOT NULL DEFAULT '',
    source_fetched_at timestamptz,
    source_hash text NOT NULL DEFAULT '',
    source_stale boolean NOT NULL DEFAULT false,
    source_changed boolean NOT NULL DEFAULT false,
    notice_id text NOT NULL DEFAULT '',
    notice_revision_hash text NOT NULL DEFAULT '',
    evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_snapshot_json jsonb,
    raw_snapshot_expires_at timestamptz,
    mode text NOT NULL DEFAULT 'shadow',
    production_send text NOT NULL DEFAULT 'blocked',
    CONSTRAINT planned_outage_decisions_ticket_revision_unique UNIQUE (ticket_id, revision),
    CONSTRAINT planned_outage_decisions_decision_check CHECK (decision IN ('MATCHED','NO_MATCH','AMBIGUOUS','INCONCLUSIVE','UNAVAILABLE')),
    CONSTRAINT planned_outage_decisions_mode_check CHECK (mode IN ('shadow','enforcement')),
    CONSTRAINT planned_outage_decisions_send_check CHECK (production_send = 'blocked')
);

CREATE INDEX IF NOT EXISTS idx_planned_outage_decisions_ticket_latest
    ON planned_outage_decisions (ticket_id, revision DESC);
CREATE INDEX IF NOT EXISTS idx_planned_outage_decisions_recorded_at
    ON planned_outage_decisions (recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_planned_outage_decisions_source_hash
    ON planned_outage_decisions (source_hash);
