CREATE TABLE IF NOT EXISTS buengkan_tester_feedback (
    receipt_id text PRIMARY KEY,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    query_hash text NOT NULL,
    verdict text NOT NULL,
    village_key text NOT NULL DEFAULT '',
    resolver_status text NOT NULL DEFAULT '',
    selected_feeder text NOT NULL DEFAULT '',
    transformer_candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
    correction_feeder text NOT NULL DEFAULT '',
    correction_transformer text NOT NULL DEFAULT '',
    mode text NOT NULL DEFAULT 'shadow',
    production_send text NOT NULL DEFAULT 'blocked',
    CONSTRAINT buengkan_tester_feedback_verdict CHECK (verdict IN ('CORRECT', 'INCORRECT', 'UNSURE')),
    CONSTRAINT buengkan_tester_feedback_mode CHECK (mode = 'shadow'),
    CONSTRAINT buengkan_tester_feedback_production_send CHECK (production_send = 'blocked'),
    CONSTRAINT buengkan_tester_feedback_query_hash CHECK (query_hash ~ '^[a-f0-9]{20,64}$')
);

CREATE INDEX IF NOT EXISTS idx_buengkan_tester_feedback_recorded_at
ON buengkan_tester_feedback (recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_buengkan_tester_feedback_village_verdict
ON buengkan_tester_feedback (village_key, verdict, recorded_at DESC);
