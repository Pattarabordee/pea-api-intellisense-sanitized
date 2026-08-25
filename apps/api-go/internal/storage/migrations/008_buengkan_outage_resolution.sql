CREATE TABLE IF NOT EXISTS buengkan_outage_resolutions (
    request_id text PRIMARY KEY,
    recorded_at timestamptz NOT NULL,
    occurred_at timestamptz NOT NULL,
    source_channel text NOT NULL,
    source_event_hash text NOT NULL,
    message_hash text NOT NULL,
    reporter_ref_hash text NOT NULL DEFAULT '',
    conversation_ref_hash text NOT NULL DEFAULT '',
    result_json jsonb NOT NULL,
    mode text NOT NULL DEFAULT 'shadow' CHECK (mode = 'shadow'),
    production_send text NOT NULL DEFAULT 'blocked' CHECK (production_send = 'blocked'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_buengkan_outage_resolutions_recorded_at
    ON buengkan_outage_resolutions (recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_buengkan_outage_resolutions_source_event_hash
    ON buengkan_outage_resolutions (source_event_hash);
