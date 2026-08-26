CREATE TABLE IF NOT EXISTS buengkan_unknown_place_observations (
    observation_hash text PRIMARY KEY,
    query_hash text NOT NULL,
    location_cell text NOT NULL DEFAULT '',
    source_channel text NOT NULL DEFAULT '',
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    mode text NOT NULL DEFAULT 'shadow',
    production_send text NOT NULL DEFAULT 'blocked',
    CHECK (mode = 'shadow'),
    CHECK (production_send = 'blocked')
);

CREATE INDEX IF NOT EXISTS idx_buengkan_unknown_place_query_cell
ON buengkan_unknown_place_observations (query_hash, location_cell, last_seen_at DESC);
