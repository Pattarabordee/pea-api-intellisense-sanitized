-- Durable async jobs for Incident Correlation Shadow v1.
-- Jobs are replayable from durable correlation_reports/evidence and never gate chatbot ACK.

CREATE TABLE IF NOT EXISTS correlation_jobs (
    job_id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL REFERENCES correlation_reports(report_id),
    job_type TEXT NOT NULL DEFAULT 'REPORT_EVIDENCE_CHANGED',
    trigger_key TEXT NOT NULL,
    trigger_evidence_revision INTEGER NOT NULL DEFAULT 1 CHECK (trigger_evidence_revision > 0),
    state TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (state IN ('PENDING','PROCESSING','RETRYING','SUCCEEDED','FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts > 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_until TIMESTAMPTZ,
    claimed_by TEXT NOT NULL DEFAULT '',
    last_error_class TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (report_id, trigger_key)
);

CREATE INDEX IF NOT EXISTS correlation_jobs_claim_idx
    ON correlation_jobs (state, available_at, lease_until, created_at);
CREATE INDEX IF NOT EXISTS correlation_jobs_report_idx
    ON correlation_jobs (report_id, created_at DESC);

-- No customer text, customer name, phone number, raw LINE identifier, or API secret is stored here.
