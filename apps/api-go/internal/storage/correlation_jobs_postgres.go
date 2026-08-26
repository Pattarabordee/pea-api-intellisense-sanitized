package storage

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// AcceptCorrelationReport atomically creates the privacy-safe correlation report,
// its immutable evidence revision, and a durable async job. It is intentionally
// separate from the customer-facing outage record: failure here must never be
// interpreted as failure to accept the customer's outage report.
func (s *PostgresStore) AcceptCorrelationReport(ctx context.Context, report CorrelationReport, evidence CorrelationEvidenceRevision, job CorrelationJob) (storedReportID string, evidenceRevision int, jobDuplicate bool, err error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return "", 0, false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	lockKey := "correlation-accept|" + strings.TrimSpace(report.SourceSystem) + "|" + strings.TrimSpace(report.TicketID)
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, lockKey); err != nil {
		return "", 0, false, err
	}

	location := jsonOrEmptyObject(report.NormalizedLocationJSON)
	createdAt := report.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}
	mode := defaultString(report.Mode, "shadow")
	productionSend := defaultString(report.ProductionSend, "blocked")
	plannedState := defaultString(report.PlannedOutageState, "NOT_CHECKED")

	err = tx.QueryRow(ctx, `
		INSERT INTO correlation_reports (
			report_id, ticket_id, source_system, source_channel, source_event_hash,
			session_ref_hash, occurred_at, normalized_location_json, core_request_id,
			planned_outage_state, mode, production_send, created_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
		ON CONFLICT (source_system, ticket_id) DO NOTHING
		RETURNING report_id
	`, report.ReportID, report.TicketID, report.SourceSystem, report.SourceChannel,
		report.SourceEventHash, report.SessionRefHash, report.OccurredAt, location,
		report.CoreRequestID, plannedState, mode, productionSend, createdAt).Scan(&storedReportID)
	if errors.Is(err, pgx.ErrNoRows) {
		err = tx.QueryRow(ctx, `
			SELECT report_id FROM correlation_reports
			WHERE source_system=$1 AND ticket_id=$2
		`, report.SourceSystem, report.TicketID).Scan(&storedReportID)
	}
	if err != nil {
		return "", 0, false, err
	}

	evidence.ReportID = storedReportID
	var existingRevision int
	err = tx.QueryRow(ctx, `
		SELECT revision FROM correlation_report_evidence_revisions
		WHERE report_id=$1 AND evidence_hash=$2
	`, storedReportID, evidence.EvidenceHash).Scan(&existingRevision)
	if err == nil {
		evidenceRevision = existingRevision
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return "", 0, false, err
	} else {
		if err := tx.QueryRow(ctx, `
			SELECT coalesce(max(revision),0)+1
			FROM correlation_report_evidence_revisions
			WHERE report_id=$1
		`, storedReportID).Scan(&evidenceRevision); err != nil {
			return "", 0, false, err
		}
		recordedAt := evidence.RecordedAt
		if recordedAt.IsZero() {
			recordedAt = time.Now().UTC()
		}
		if _, err := tx.Exec(ctx, `
			INSERT INTO correlation_report_evidence_revisions (
				report_id, revision, evidence_hash, topology_json, location_json,
				freshness_json, planned_outage_state, evidence_quality, recorded_at, source_version
			) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
		`, storedReportID, evidenceRevision, evidence.EvidenceHash,
			jsonOrEmptyObject(evidence.TopologyJSON), jsonOrEmptyObject(evidence.LocationJSON),
			jsonOrEmptyObject(evidence.FreshnessJSON), defaultString(evidence.PlannedOutageState, "NOT_CHECKED"),
			defaultString(evidence.EvidenceQuality, "PROVISIONAL"), recordedAt, evidence.SourceVersion); err != nil {
			return "", 0, false, err
		}
	}

	job.ReportID = storedReportID
	job.TriggerEvidenceRevision = evidenceRevision
	if job.CreatedAt.IsZero() {
		job.CreatedAt = time.Now().UTC()
	}
	if job.AvailableAt.IsZero() {
		job.AvailableAt = job.CreatedAt
	}
	if job.MaxAttempts <= 0 {
		job.MaxAttempts = 5
	}
	state := defaultString(job.State, "PENDING")
	jobType := defaultString(job.JobType, "REPORT_EVIDENCE_CHANGED")
	tag, err := tx.Exec(ctx, `
		INSERT INTO correlation_jobs (
			job_id, report_id, job_type, trigger_key, trigger_evidence_revision,
			state, attempt_count, max_attempts, available_at, created_at, updated_at
		) VALUES ($1,$2,$3,$4,$5,$6,0,$7,$8,$9,$9)
		ON CONFLICT (report_id, trigger_key) DO NOTHING
	`, job.JobID, storedReportID, jobType, job.TriggerKey, evidenceRevision,
		state, job.MaxAttempts, job.AvailableAt, job.CreatedAt)
	if err != nil {
		return "", 0, false, err
	}
	jobDuplicate = tag.RowsAffected() == 0

	if err := tx.Commit(ctx); err != nil {
		return "", 0, false, err
	}
	return storedReportID, evidenceRevision, jobDuplicate, nil
}

func (s *PostgresStore) ClaimCorrelationJob(ctx context.Context, workerID string, lease time.Duration) (*CorrelationJob, error) {
	if lease <= 0 {
		lease = 30 * time.Second
	}
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, `
		UPDATE correlation_jobs
		SET state='FAILED', last_error_class=CASE WHEN last_error_class='' THEN 'MAX_ATTEMPTS_EXHAUSTED' ELSE last_error_class END,
			lease_until=NULL, claimed_by='', updated_at=now(), completed_at=coalesce(completed_at, now())
		WHERE attempt_count >= max_attempts
		  AND state IN ('PENDING','RETRYING','PROCESSING')
		  AND (state <> 'PROCESSING' OR lease_until IS NULL OR lease_until <= now())
	`); err != nil {
		return nil, err
	}

	var job CorrelationJob
	err = tx.QueryRow(ctx, `
		WITH candidate AS (
			SELECT job_id
			FROM correlation_jobs
			WHERE attempt_count < max_attempts
			  AND available_at <= now()
			  AND (
				state IN ('PENDING','RETRYING')
				OR (state='PROCESSING' AND (lease_until IS NULL OR lease_until <= now()))
			  )
			ORDER BY available_at, created_at, job_id
			FOR UPDATE SKIP LOCKED
			LIMIT 1
		)
		UPDATE correlation_jobs j
		SET state='PROCESSING', attempt_count=j.attempt_count+1,
			lease_until=now()+($2 * interval '1 millisecond'), claimed_by=$1, updated_at=now()
		FROM candidate c
		WHERE j.job_id=c.job_id
		RETURNING j.job_id,j.report_id,j.job_type,j.trigger_key,j.trigger_evidence_revision,
			j.state,j.attempt_count,j.max_attempts,j.available_at,j.lease_until,j.claimed_by,
			j.last_error_class,j.created_at,j.updated_at,j.completed_at
	`, workerID, lease.Milliseconds()).Scan(
		&job.JobID, &job.ReportID, &job.JobType, &job.TriggerKey, &job.TriggerEvidenceRevision,
		&job.State, &job.AttemptCount, &job.MaxAttempts, &job.AvailableAt, &job.LeaseUntil,
		&job.ClaimedBy, &job.LastErrorClass, &job.CreatedAt, &job.UpdatedAt, &job.CompletedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}
	return &job, nil
}

func (s *PostgresStore) CompleteCorrelationJob(ctx context.Context, jobID, workerID string) error {
	tag, err := s.pool.Exec(ctx, `
		UPDATE correlation_jobs
		SET state='SUCCEEDED', lease_until=NULL, claimed_by='', last_error_class='',
			updated_at=now(), completed_at=now()
		WHERE job_id=$1 AND state='PROCESSING' AND claimed_by=$2
	`, jobID, workerID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() != 1 {
		return fmt.Errorf("correlation job completion lost lease")
	}
	return nil
}

func (s *PostgresStore) RetryOrFailCorrelationJob(ctx context.Context, job CorrelationJob, workerID, errorClass string, nextAvailable time.Time) (string, error) {
	if nextAvailable.IsZero() {
		nextAvailable = time.Now().UTC()
	}
	state := "RETRYING"
	completedExpr := "NULL"
	if job.AttemptCount >= job.MaxAttempts {
		state = "FAILED"
		completedExpr = "now()"
	}
	query := `
		UPDATE correlation_jobs
		SET state=$3, available_at=$4, lease_until=NULL, claimed_by='', last_error_class=$5,
			updated_at=now(), completed_at=` + completedExpr + `
		WHERE job_id=$1 AND state='PROCESSING' AND claimed_by=$2
	`
	tag, err := s.pool.Exec(ctx, query, job.JobID, workerID, state, nextAvailable, errorClass)
	if err != nil {
		return "", err
	}
	if tag.RowsAffected() != 1 {
		return "", fmt.Errorf("correlation job retry lost lease")
	}
	return state, nil
}

func (s *PostgresStore) GetCorrelationReportSnapshot(ctx context.Context, reportID string) (*CorrelationReportSnapshot, error) {
	var out CorrelationReportSnapshot
	err := s.pool.QueryRow(ctx, `
		SELECT r.report_id,r.ticket_id,r.source_system,r.source_channel,r.source_event_hash,
			r.session_ref_hash,r.occurred_at,r.normalized_location_json,r.core_request_id,
			r.planned_outage_state,r.mode,r.production_send,r.created_at,
			e.revision,e.evidence_hash,e.topology_json,e.location_json,e.freshness_json,
			e.planned_outage_state,e.evidence_quality,e.recorded_at,e.source_version
		FROM correlation_reports r
		JOIN LATERAL (
			SELECT * FROM correlation_report_evidence_revisions
			WHERE report_id=r.report_id ORDER BY revision DESC LIMIT 1
		) e ON true
		WHERE r.report_id=$1
	`, reportID).Scan(
		&out.Report.ReportID, &out.Report.TicketID, &out.Report.SourceSystem, &out.Report.SourceChannel,
		&out.Report.SourceEventHash, &out.Report.SessionRefHash, &out.Report.OccurredAt,
		&out.Report.NormalizedLocationJSON, &out.Report.CoreRequestID, &out.Report.PlannedOutageState,
		&out.Report.Mode, &out.Report.ProductionSend, &out.Report.CreatedAt,
		&out.Evidence.Revision, &out.Evidence.EvidenceHash, &out.Evidence.TopologyJSON,
		&out.Evidence.LocationJSON, &out.Evidence.FreshnessJSON, &out.Evidence.PlannedOutageState,
		&out.Evidence.EvidenceQuality, &out.Evidence.RecordedAt, &out.Evidence.SourceVersion,
	)
	out.Evidence.ReportID = out.Report.ReportID
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &out, nil
}

func (s *PostgresStore) ListCorrelationReportSnapshots(ctx context.Context, limit int) ([]CorrelationReportSnapshot, error) {
	if limit <= 0 || limit > 2000 {
		limit = 500
	}
	rows, err := s.pool.Query(ctx, `
		SELECT r.report_id,r.ticket_id,r.source_system,r.source_channel,r.source_event_hash,
			r.session_ref_hash,r.occurred_at,r.normalized_location_json,r.core_request_id,
			r.planned_outage_state,r.mode,r.production_send,r.created_at,
			e.revision,e.evidence_hash,e.topology_json,e.location_json,e.freshness_json,
			e.planned_outage_state,e.evidence_quality,e.recorded_at,e.source_version
		FROM correlation_reports r
		JOIN LATERAL (
			SELECT * FROM correlation_report_evidence_revisions
			WHERE report_id=r.report_id ORDER BY revision DESC LIMIT 1
		) e ON true
		ORDER BY r.occurred_at DESC, r.report_id
		LIMIT $1
	`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]CorrelationReportSnapshot, 0)
	for rows.Next() {
		var out CorrelationReportSnapshot
		if err := rows.Scan(
			&out.Report.ReportID, &out.Report.TicketID, &out.Report.SourceSystem, &out.Report.SourceChannel,
			&out.Report.SourceEventHash, &out.Report.SessionRefHash, &out.Report.OccurredAt,
			&out.Report.NormalizedLocationJSON, &out.Report.CoreRequestID, &out.Report.PlannedOutageState,
			&out.Report.Mode, &out.Report.ProductionSend, &out.Report.CreatedAt,
			&out.Evidence.Revision, &out.Evidence.EvidenceHash, &out.Evidence.TopologyJSON,
			&out.Evidence.LocationJSON, &out.Evidence.FreshnessJSON, &out.Evidence.PlannedOutageState,
			&out.Evidence.EvidenceQuality, &out.Evidence.RecordedAt, &out.Evidence.SourceVersion,
		); err != nil {
			return nil, err
		}
		out.Evidence.ReportID = out.Report.ReportID
		result = append(result, out)
	}
	return result, rows.Err()
}

func (s *PostgresStore) ListLatestCorrelationMemberships(ctx context.Context) ([]CorrelationMembershipRevision, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT DISTINCT ON (report_id)
			report_id,cluster_id,membership_revision,membership_state,assignment_reason,
			confidence_score,confidence_level,engine_version,decision_hash,created_at
		FROM correlation_cluster_membership_revisions
		ORDER BY report_id,membership_revision DESC
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []CorrelationMembershipRevision{}
	for rows.Next() {
		var item CorrelationMembershipRevision
		if err := rows.Scan(&item.ReportID, &item.ClusterID, &item.MembershipRevision,
			&item.MembershipState, &item.AssignmentReason, &item.ConfidenceScore,
			&item.ConfidenceLevel, &item.EngineVersion, &item.DecisionHash, &item.CreatedAt); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *PostgresStore) GetLatestCorrelationClusterRevision(ctx context.Context, clusterID string) (*CorrelationClusterRevision, error) {
	var item CorrelationClusterRevision
	err := s.pool.QueryRow(ctx, `
		SELECT cluster_id,revision,decision_hash,lifecycle_state,correlation_status,
			confidence_score,confidence_level,raw_report_count,unique_reporter_count,
			topology_hypothesis_json,evidence_summary_json,engine_version,created_at
		FROM correlation_cluster_revisions
		WHERE cluster_id=$1 ORDER BY revision DESC LIMIT 1
	`, clusterID).Scan(
		&item.ClusterID, &item.Revision, &item.DecisionHash, &item.LifecycleState,
		&item.CorrelationStatus, &item.ConfidenceScore, &item.ConfidenceLevel,
		&item.RawReportCount, &item.UniqueReporterCount, &item.TopologyHypothesisJSON,
		&item.EvidenceSummaryJSON, &item.EngineVersion, &item.CreatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &item, nil
}

func (s *PostgresStore) GetLatestCorrelationMembership(ctx context.Context, reportID string) (*CorrelationMembershipRevision, error) {
	var item CorrelationMembershipRevision
	err := s.pool.QueryRow(ctx, `
		SELECT report_id,cluster_id,membership_revision,membership_state,assignment_reason,
			confidence_score,confidence_level,engine_version,decision_hash,created_at
		FROM correlation_cluster_membership_revisions
		WHERE report_id=$1
		ORDER BY membership_revision DESC
		LIMIT 1
	`, reportID).Scan(
		&item.ReportID, &item.ClusterID, &item.MembershipRevision,
		&item.MembershipState, &item.AssignmentReason, &item.ConfidenceScore,
		&item.ConfidenceLevel, &item.EngineVersion, &item.DecisionHash, &item.CreatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &item, nil
}

func (s *PostgresStore) GetLatestCorrelationJobForReport(ctx context.Context, reportID string) (*CorrelationJob, error) {
	var job CorrelationJob
	err := s.pool.QueryRow(ctx, `
		SELECT job_id,report_id,job_type,trigger_key,trigger_evidence_revision,
			state,attempt_count,max_attempts,available_at,lease_until,claimed_by,
			last_error_class,created_at,updated_at,completed_at
		FROM correlation_jobs
		WHERE report_id=$1
		ORDER BY created_at DESC, job_id DESC
		LIMIT 1
	`, reportID).Scan(
		&job.JobID, &job.ReportID, &job.JobType, &job.TriggerKey, &job.TriggerEvidenceRevision,
		&job.State, &job.AttemptCount, &job.MaxAttempts, &job.AvailableAt, &job.LeaseUntil,
		&job.ClaimedBy, &job.LastErrorClass, &job.CreatedAt, &job.UpdatedAt, &job.CompletedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	return &job, nil
}

func (s *PostgresStore) CorrelationJobCounts(ctx context.Context) (map[string]int64, error) {
	rows, err := s.pool.Query(ctx, `SELECT state,count(*)::bigint FROM correlation_jobs GROUP BY state`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := map[string]int64{}
	for rows.Next() {
		var state string
		var count int64
		if err := rows.Scan(&state, &count); err != nil {
			return nil, err
		}
		result[state] = count
	}
	return result, rows.Err()
}

func correlationJSONMap(raw json.RawMessage) map[string]any {
	out := map[string]any{}
	_ = json.Unmarshal(raw, &out)
	return out
}

func (s *PostgresStore) AcquireCorrelationScopeLocks(ctx context.Context, scopeKeys []string) (func(), error) {
	keys := append([]string(nil), scopeKeys...)
	sort.Strings(keys)
	conn, err := s.pool.Acquire(ctx)
	if err != nil {
		return nil, err
	}
	locked := make([]string, 0, len(keys))
	for _, scopeKey := range keys {
		scopeKey = strings.TrimSpace(scopeKey)
		if scopeKey == "" {
			continue
		}
		lockKey := "correlation-scope|" + scopeKey
		if _, err := conn.Exec(ctx, `SELECT pg_advisory_lock(hashtext($1))`, lockKey); err != nil {
			for i := len(locked) - 1; i >= 0; i-- {
				_, _ = conn.Exec(context.Background(), `SELECT pg_advisory_unlock(hashtext($1))`, locked[i])
			}
			conn.Release()
			return nil, err
		}
		locked = append(locked, lockKey)
	}
	released := false
	return func() {
		if released {
			return
		}
		released = true
		unlockCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		for i := len(locked) - 1; i >= 0; i-- {
			_, _ = conn.Exec(unlockCtx, `SELECT pg_advisory_unlock(hashtext($1))`, locked[i])
		}
		conn.Release()
	}, nil
}
