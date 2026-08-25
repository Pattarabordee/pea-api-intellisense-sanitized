CREATE TABLE IF NOT EXISTS buengkan_secondary_validation (
    receipt_id TEXT PRIMARY KEY,
    recorded_at TIMESTAMPTZ NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('POI','ROAD_SOI')),
    source_ref TEXT NOT NULL,
    source_label TEXT NOT NULL,
    validator_ref TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('CORRECT','INCORRECT','UNSURE')),
    candidate_transformers JSONB NOT NULL DEFAULT '[]'::jsonb,
    selected_transformer TEXT NOT NULL DEFAULT '',
    correction_transformer TEXT NOT NULL DEFAULT '',
    correction_feeder TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'shadow' CHECK (mode = 'shadow'),
    production_send TEXT NOT NULL DEFAULT 'blocked' CHECK (production_send = 'blocked')
);

CREATE INDEX IF NOT EXISTS idx_buengkan_secondary_validation_source_ref
    ON buengkan_secondary_validation (source_ref, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_buengkan_secondary_validation_recorded_at
    ON buengkan_secondary_validation (recorded_at DESC);
