package storage

import (
	"context"
	"encoding/json"
	"errors"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

func (s *PostgresStore) UpsertCorrelationReport(ctx context.Context, report CorrelationReport) (storedReportID string, duplicate bool, err error) {
	location := report.NormalizedLocationJSON
	if len(location) == 0 {
		location = json.RawMessage(`{}`)
	}
	createdAt := report.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}
	mode := strings.TrimSpace(report.Mode)
	if mode == "" {
		mode = "shadow"
	}
	productionSend := strings.TrimSpace(report.ProductionSend)
	if productionSend == "" {
		productionSend = "blocked"
	}
	plannedState := strings.TrimSpace(report.PlannedOutageState)
	if plannedState == "" {
		plannedState = "NOT_CHECKED"
	}

	var insertedID string
	err = s.pool.QueryRow(ctx, `
		INSERT INTO correlation_reports (
			report_id, ticket_id, source_system, source_channel, source_event_hash,
			session_ref_hash, occurred_at, normalized_location_json, core_request_id,
			planned_outage_state, mode, production_send, created_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
		ON CONFLICT (source_system, ticket_id) DO NOTHING
		RETURNING report_id
	`, report.ReportID, report.TicketID, report.SourceSystem, report.SourceChannel,
		report.SourceEventHash, report.SessionRefHash, report.OccurredAt, location,
		report.CoreRequestID, plannedState, mode, productionSend, createdAt).Scan(&insertedID)
	if err == nil {
		return insertedID, false, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return "", false, err
	}

	var existingID string
	if err := s.pool.QueryRow(ctx, `
		SELECT report_id
		FROM correlation_reports
		WHERE source_system=$1 AND ticket_id=$2
	`, report.SourceSystem, report.TicketID).Scan(&existingID); err != nil {
		return "", false, err
	}
	return existingID, true, nil
}

func (s *PostgresStore) InsertCorrelationEvidenceRevision(ctx context.Context, revision CorrelationEvidenceRevision) (storedRevision int, duplicate bool, err error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return 0, false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, "correlation-evidence|"+revision.ReportID); err != nil {
		return 0, false, err
	}
	var existing int
	err = tx.QueryRow(ctx, `
		SELECT revision FROM correlation_report_evidence_revisions
		WHERE report_id=$1 AND evidence_hash=$2
	`, revision.ReportID, revision.EvidenceHash).Scan(&existing)
	if err == nil {
		return existing, true, tx.Commit(ctx)
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return 0, false, err
	}
	var next int
	if err := tx.QueryRow(ctx, `
		SELECT coalesce(max(revision),0)+1
		FROM correlation_report_evidence_revisions
		WHERE report_id=$1
	`, revision.ReportID).Scan(&next); err != nil {
		return 0, false, err
	}
	topology := jsonOrEmptyObject(revision.TopologyJSON)
	location := jsonOrEmptyObject(revision.LocationJSON)
	freshness := jsonOrEmptyObject(revision.FreshnessJSON)
	recordedAt := revision.RecordedAt
	if recordedAt.IsZero() {
		recordedAt = time.Now().UTC()
	}
	plannedState := defaultString(revision.PlannedOutageState, "NOT_CHECKED")
	quality := defaultString(revision.EvidenceQuality, "PROVISIONAL")
	if _, err := tx.Exec(ctx, `
		INSERT INTO correlation_report_evidence_revisions (
			report_id, revision, evidence_hash, topology_json, location_json,
			freshness_json, planned_outage_state, evidence_quality, recorded_at, source_version
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
	`, revision.ReportID, next, revision.EvidenceHash, topology, location, freshness,
		plannedState, quality, recordedAt, revision.SourceVersion); err != nil {
		return 0, false, err
	}
	return next, false, tx.Commit(ctx)
}

func (s *PostgresStore) InsertCorrelationRelationship(ctx context.Context, relationship CorrelationRelationship) (storedRevision int, duplicate bool, err error) {
	a, b := canonicalCorrelationPair(relationship.ReportAID, relationship.ReportBID)
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return 0, false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	lockKey := "correlation-relationship|" + a + "|" + b
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, lockKey); err != nil {
		return 0, false, err
	}
	var existing int
	err = tx.QueryRow(ctx, `SELECT revision FROM correlation_report_relationships WHERE decision_hash=$1`, relationship.DecisionHash).Scan(&existing)
	if err == nil {
		return existing, true, tx.Commit(ctx)
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return 0, false, err
	}
	var next int
	if err := tx.QueryRow(ctx, `
		SELECT coalesce(max(revision),0)+1
		FROM correlation_report_relationships
		WHERE report_a_id=$1 AND report_b_id=$2
	`, a, b).Scan(&next); err != nil {
		return 0, false, err
	}
	createdAt := relationship.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}
	state := defaultString(relationship.RelationshipState, "SUSPECTED")
	evidence := jsonOrEmptyObject(relationship.EvidenceJSON)
	if _, err := tx.Exec(ctx, `
		INSERT INTO correlation_report_relationships (
			report_a_id, report_b_id, revision, decision_hash, confidence_score,
			confidence_level, hard_veto, relationship_state, evidence_json,
			engine_version, created_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
	`, a, b, next, relationship.DecisionHash, relationship.ConfidenceScore,
		relationship.ConfidenceLevel, relationship.HardVeto, state, evidence,
		relationship.EngineVersion, createdAt); err != nil {
		return 0, false, err
	}
	return next, false, tx.Commit(ctx)
}

func (s *PostgresStore) InsertCorrelationCluster(ctx context.Context, cluster CorrelationCluster) (duplicate bool, err error) {
	createdAt := cluster.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}
	mode := defaultString(cluster.Mode, "shadow")
	tag, err := s.pool.Exec(ctx, `
		INSERT INTO correlation_clusters (cluster_id, created_at, created_engine_version, mode)
		VALUES ($1,$2,$3,$4)
		ON CONFLICT (cluster_id) DO NOTHING
	`, cluster.ClusterID, createdAt, cluster.CreatedEngineVersion, mode)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() == 0, nil
}

func (s *PostgresStore) InsertCorrelationClusterRevision(ctx context.Context, revision CorrelationClusterRevision) (storedRevision int, duplicate bool, err error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return 0, false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, "correlation-cluster|"+revision.ClusterID); err != nil {
		return 0, false, err
	}
	var existing int
	err = tx.QueryRow(ctx, `SELECT revision FROM correlation_cluster_revisions WHERE decision_hash=$1`, revision.DecisionHash).Scan(&existing)
	if err == nil {
		return existing, true, tx.Commit(ctx)
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return 0, false, err
	}
	var current int
	if err := tx.QueryRow(ctx, `
		SELECT coalesce(max(revision),0)
		FROM correlation_cluster_revisions
		WHERE cluster_id=$1
	`, revision.ClusterID).Scan(&current); err != nil {
		return 0, false, err
	}
	if revision.ExpectedRevision != nil && current != *revision.ExpectedRevision {
		return 0, false, ErrCorrelationRevisionConflict
	}
	next := current + 1
	createdAt := revision.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}
	status := defaultString(revision.CorrelationStatus, "SUSPECTED_RELATED")
	if _, err := tx.Exec(ctx, `
		INSERT INTO correlation_cluster_revisions (
			cluster_id, revision, decision_hash, lifecycle_state, correlation_status,
			confidence_score, confidence_level, raw_report_count, unique_reporter_count,
			topology_hypothesis_json, evidence_summary_json, engine_version, created_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
	`, revision.ClusterID, next, revision.DecisionHash, revision.LifecycleState, status,
		revision.ConfidenceScore, revision.ConfidenceLevel, revision.RawReportCount,
		revision.UniqueReporterCount, jsonOrEmptyObject(revision.TopologyHypothesisJSON),
		jsonOrEmptyObject(revision.EvidenceSummaryJSON), revision.EngineVersion, createdAt); err != nil {
		return 0, false, err
	}
	return next, false, tx.Commit(ctx)
}

func (s *PostgresStore) InsertCorrelationMembershipRevision(ctx context.Context, membership CorrelationMembershipRevision) (storedRevision int, duplicate bool, err error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return 0, false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, "correlation-membership|"+membership.ReportID); err != nil {
		return 0, false, err
	}
	var existing int
	err = tx.QueryRow(ctx, `SELECT membership_revision FROM correlation_cluster_membership_revisions WHERE decision_hash=$1`, membership.DecisionHash).Scan(&existing)
	if err == nil {
		return existing, true, tx.Commit(ctx)
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return 0, false, err
	}
	var next int
	if err := tx.QueryRow(ctx, `
		SELECT coalesce(max(membership_revision),0)+1
		FROM correlation_cluster_membership_revisions
		WHERE report_id=$1
	`, membership.ReportID).Scan(&next); err != nil {
		return 0, false, err
	}
	createdAt := membership.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}
	if _, err := tx.Exec(ctx, `
		INSERT INTO correlation_cluster_membership_revisions (
			report_id, cluster_id, membership_revision, membership_state, assignment_reason,
			confidence_score, confidence_level, engine_version, decision_hash, created_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
	`, membership.ReportID, membership.ClusterID, next, membership.MembershipState,
		membership.AssignmentReason, membership.ConfidenceScore, membership.ConfidenceLevel,
		membership.EngineVersion, membership.DecisionHash, createdAt); err != nil {
		return 0, false, err
	}
	return next, false, tx.Commit(ctx)
}

func (s *PostgresStore) InsertCorrelationClusterLineage(ctx context.Context, lineage CorrelationClusterLineage) (duplicate bool, err error) {
	createdAt := lineage.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}
	tag, err := s.pool.Exec(ctx, `
		INSERT INTO correlation_cluster_lineage (
			parent_cluster_id, child_cluster_id, relation_type, parent_revision,
			child_revision, reason, engine_version, created_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
		ON CONFLICT (parent_cluster_id, child_cluster_id, relation_type, parent_revision, child_revision) DO NOTHING
	`, lineage.ParentClusterID, lineage.ChildClusterID, lineage.RelationType,
		lineage.ParentRevision, lineage.ChildRevision, lineage.Reason, lineage.EngineVersion, createdAt)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() == 0, nil
}

func canonicalCorrelationPair(a, b string) (string, string) {
	values := []string{strings.TrimSpace(a), strings.TrimSpace(b)}
	sort.Strings(values)
	return values[0], values[1]
}

func jsonOrEmptyObject(value json.RawMessage) json.RawMessage {
	if len(value) == 0 {
		return json.RawMessage(`{}`)
	}
	return value
}

func defaultString(value, fallback string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return fallback
	}
	return value
}
