-- Incident Correlation Shadow v1 foundation.
-- This schema is intentionally append-oriented and customer-safe.
-- It does not create Operational Incidents, work orders, or customer-facing confirmations.

CREATE TABLE IF NOT EXISTS correlation_reports (
    report_id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_channel TEXT NOT NULL,
    source_event_hash TEXT NOT NULL,
    session_ref_hash TEXT NOT NULL DEFAULT '',
    occurred_at TIMESTAMPTZ NOT NULL,
    normalized_location_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    core_request_id TEXT NOT NULL DEFAULT '',
    planned_outage_state TEXT NOT NULL DEFAULT 'NOT_CHECKED',
    mode TEXT NOT NULL DEFAULT 'shadow',
    production_send TEXT NOT NULL DEFAULT 'blocked',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_system, ticket_id)
);

CREATE INDEX IF NOT EXISTS correlation_reports_occurred_at_idx
    ON correlation_reports (occurred_at DESC);
CREATE INDEX IF NOT EXISTS correlation_reports_ticket_idx
    ON correlation_reports (ticket_id);

CREATE TABLE IF NOT EXISTS correlation_report_evidence_revisions (
    report_id TEXT NOT NULL REFERENCES correlation_reports(report_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    evidence_hash TEXT NOT NULL,
    topology_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    location_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    freshness_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    planned_outage_state TEXT NOT NULL DEFAULT 'NOT_CHECKED',
    evidence_quality TEXT NOT NULL DEFAULT 'PROVISIONAL',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_version TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (report_id, revision),
    UNIQUE (report_id, evidence_hash)
);

CREATE TABLE IF NOT EXISTS correlation_report_relationships (
    report_a_id TEXT NOT NULL REFERENCES correlation_reports(report_id),
    report_b_id TEXT NOT NULL REFERENCES correlation_reports(report_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    decision_hash TEXT NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 100),
    confidence_level TEXT NOT NULL CHECK (confidence_level IN ('LOW','MEDIUM','HIGH')),
    hard_veto BOOLEAN NOT NULL DEFAULT FALSE,
    relationship_state TEXT NOT NULL DEFAULT 'SUSPECTED',
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    engine_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (report_a_id, report_b_id, revision),
    UNIQUE (decision_hash),
    CHECK (report_a_id < report_b_id)
);

CREATE INDEX IF NOT EXISTS correlation_relationships_a_idx
    ON correlation_report_relationships (report_a_id, revision DESC);
CREATE INDEX IF NOT EXISTS correlation_relationships_b_idx
    ON correlation_report_relationships (report_b_id, revision DESC);

CREATE TABLE IF NOT EXISTS correlation_clusters (
    cluster_id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_engine_version TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'shadow'
);

CREATE TABLE IF NOT EXISTS correlation_cluster_revisions (
    cluster_id TEXT NOT NULL REFERENCES correlation_clusters(cluster_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    decision_hash TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('ACTIVE','QUIET','CLOSED','REOPENED','SPLIT','SUPERSEDED_BY_MERGE')),
    correlation_status TEXT NOT NULL DEFAULT 'SUSPECTED_RELATED',
    confidence_score DOUBLE PRECISION NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 100),
    confidence_level TEXT NOT NULL CHECK (confidence_level IN ('LOW','MEDIUM','HIGH')),
    raw_report_count INTEGER NOT NULL DEFAULT 0 CHECK (raw_report_count >= 0),
    unique_reporter_count INTEGER NOT NULL DEFAULT 0 CHECK (unique_reporter_count >= 0),
    topology_hypothesis_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    engine_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cluster_id, revision),
    UNIQUE (decision_hash)
);

CREATE TABLE IF NOT EXISTS correlation_cluster_membership_revisions (
    report_id TEXT NOT NULL REFERENCES correlation_reports(report_id),
    cluster_id TEXT NOT NULL REFERENCES correlation_clusters(cluster_id),
    membership_revision INTEGER NOT NULL CHECK (membership_revision > 0),
    membership_state TEXT NOT NULL CHECK (membership_state IN ('ACTIVE','REMOVED','REASSIGNMENT_PENDING')),
    assignment_reason TEXT NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 100),
    confidence_level TEXT NOT NULL CHECK (confidence_level IN ('LOW','MEDIUM','HIGH')),
    engine_version TEXT NOT NULL,
    decision_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (report_id, membership_revision),
    UNIQUE (decision_hash)
);

CREATE INDEX IF NOT EXISTS correlation_membership_cluster_idx
    ON correlation_cluster_membership_revisions (cluster_id, created_at DESC);

CREATE TABLE IF NOT EXISTS correlation_cluster_lineage (
    lineage_id BIGSERIAL PRIMARY KEY,
    parent_cluster_id TEXT NOT NULL REFERENCES correlation_clusters(cluster_id),
    child_cluster_id TEXT NOT NULL REFERENCES correlation_clusters(cluster_id),
    relation_type TEXT NOT NULL CHECK (relation_type IN ('MERGE','SPLIT','RECURRENCE','RELATED')),
    parent_revision INTEGER NOT NULL DEFAULT 0,
    child_revision INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    engine_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (parent_cluster_id, child_cluster_id, relation_type, parent_revision, child_revision)
);

-- Phase 1 is Shadow-only. Runtime wiring and async durable jobs are added in later phases.
