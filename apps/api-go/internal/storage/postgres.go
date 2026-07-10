package storage

import (
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed migrations/*.sql
var migrationFS embed.FS

type PostgresStore struct {
	pool *pgxpool.Pool
}

func NewPostgresStore(ctx context.Context, databaseURL string) (*PostgresStore, error) {
	if databaseURL == "" {
		return nil, errors.New("DATABASE_URL is required")
	}
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 8
	cfg.MinConns = 1
	cfg.MaxConnLifetime = 30 * time.Minute
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	return &PostgresStore{pool: pool}, nil
}

func (s *PostgresStore) Close() {
	s.pool.Close()
}

func (s *PostgresStore) Init(ctx context.Context) error {
	if _, err := s.pool.Exec(ctx, `CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())`); err != nil {
		return err
	}
	entries, err := migrationFS.ReadDir("migrations")
	if err != nil {
		return err
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		if !entry.IsDir() {
			names = append(names, entry.Name())
		}
	}
	sort.Strings(names)
	for _, name := range names {
		applied, err := s.migrationApplied(ctx, name)
		if err != nil {
			return err
		}
		if applied {
			continue
		}
		sqlBytes, err := migrationFS.ReadFile("migrations/" + name)
		if err != nil {
			return err
		}
		tx, err := s.pool.Begin(ctx)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, string(sqlBytes)); err != nil {
			_ = tx.Rollback(ctx)
			return fmt.Errorf("migration %s failed: %w", name, err)
		}
		if _, err := tx.Exec(ctx, `INSERT INTO schema_migrations (version) VALUES ($1)`, name); err != nil {
			_ = tx.Rollback(ctx)
			return err
		}
		if err := tx.Commit(ctx); err != nil {
			return err
		}
	}
	return nil
}

func (s *PostgresStore) migrationApplied(ctx context.Context, version string) (bool, error) {
	var exists bool
	err := s.pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version=$1)`, version).Scan(&exists)
	return exists, err
}

func (s *PostgresStore) Health(ctx context.Context) error {
	return s.pool.Ping(ctx)
}

func (s *PostgresStore) InsertInbound(ctx context.Context, request InboundRequest, truth TruthObservation, callback Callback, evidence EvidenceTrace, etr ETRCandidate, send SendDecision, outbox CallbackOutbox) (bool, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	tag, err := tx.Exec(
		ctx,
		`INSERT INTO ais_inbound_requests (
			request_id, received_at, meter_hash, meter_last4, detected_at, detected_at_original,
			timestamp_quality, province, district, subdistrict, request_json, response_json,
			callback_status, mode, production_send
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'shadow','blocked')
		ON CONFLICT (request_id) DO NOTHING`,
		request.RequestID,
		request.ReceivedAt,
		request.MeterHash,
		request.MeterLast4,
		request.DetectedAt,
		request.DetectedAtOriginal,
		request.TimestampQuality,
		request.Province,
		request.District,
		request.Subdistrict,
		request.RequestJSON,
		request.ResponseJSON,
		request.CallbackStatus,
	)
	if err != nil {
		return false, err
	}
	duplicate := tag.RowsAffected() == 0
	if duplicate {
		return true, tx.Commit(ctx)
	}
	if err := insertTruthObservation(ctx, tx, truth); err != nil {
		return false, err
	}
	if err := upsertTruthInterval(ctx, tx, truth); err != nil {
		return false, err
	}
	if err := insertCallback(ctx, tx, callback); err != nil {
		return false, err
	}
	if err := insertEvidence(ctx, tx, evidence); err != nil {
		return false, err
	}
	if err := insertETR(ctx, tx, etr); err != nil {
		return false, err
	}
	decisionID, err := insertSendDecision(ctx, tx, send)
	if err != nil {
		return false, err
	}
	if err := insertCallbackOutbox(ctx, tx, decisionID, outbox); err != nil {
		return false, err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO audit_events (event_type, request_id, details_json) VALUES ('request_received', $1, $2)`, request.RequestID, request.ResponseJSON); err != nil {
		return false, err
	}
	return duplicate, tx.Commit(ctx)
}

func (s *PostgresStore) InsertCallback(ctx context.Context, callback Callback) error {
	_, err := s.pool.Exec(
		ctx,
		`INSERT INTO ais_inbound_callbacks (request_id, callback_url, mode, payload_json, status, status_code, response_text, sent_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
		callback.RequestID,
		nullIfEmpty(callback.CallbackURL),
		callback.Mode,
		callback.PayloadJSON,
		callback.Status,
		callback.StatusCode,
		nullIfEmpty(callback.ResponseText),
		callback.SentAt,
	)
	return err
}

func (s *PostgresStore) GetStatus(ctx context.Context, requestID string) (*RequestStatus, error) {
	rows, err := s.queryStatuses(ctx, `WHERE r.request_id = $1`, 1, requestID)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, ErrNotFound
	}
	return &rows[0], nil
}

func (s *PostgresStore) ListStatuses(ctx context.Context, limit int) ([]RequestStatus, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	return s.queryStatuses(ctx, "", limit)
}

func (s *PostgresStore) ListTruthIntervals(ctx context.Context, status string, limit int) ([]TruthInterval, error) {
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	status = strings.ToUpper(strings.TrimSpace(status))
	where := ""
	args := []any{}
	if status != "" && status != "ALL" {
		where = "WHERE pair_status = $1"
		args = append(args, status)
	}
	query := `
	SELECT interval_id, source, coalesce(outage_request_id, ''), coalesce(restore_request_id, ''),
		correlation_hash, meter_hash, meter_last4, site_hash, site_last4, outage_at, restore_at,
		duration_minutes::float8, pair_status, bridge_status, semantic_mapping_version, evidence_json, production_send, created_at, updated_at
	FROM ais_truth_intervals
	` + where + `
	ORDER BY outage_at DESC, id DESC
	LIMIT $` + fmt.Sprint(len(args)+1)
	args = append(args, limit)
	rows, err := s.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []TruthInterval{}
	for rows.Next() {
		var item TruthInterval
		if err := rows.Scan(
			&item.IntervalID,
			&item.Source,
			&item.OutageRequestID,
			&item.RestoreRequestID,
			&item.CorrelationHash,
			&item.MeterHash,
			&item.MeterLast4,
			&item.SiteHash,
			&item.SiteLast4,
			&item.OutageAt,
			&item.RestoreAt,
			&item.DurationMinutes,
			&item.PairStatus,
			&item.BridgeStatus,
			&item.SemanticMappingVersion,
			&item.EvidenceJSON,
			&item.ProductionSend,
			&item.CreatedAt,
			&item.UpdatedAt,
		); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func (s *PostgresStore) Metrics(ctx context.Context) (*MetricsSnapshot, error) {
	snapshot := &MetricsSnapshot{
		CallbackCounts:           map[string]int64{},
		TruthValidationCounts:    map[string]int64{},
		TruthEventSemanticCounts: map[string]int64{},
	}
	var latestReceivedAt time.Time
	if err := s.pool.QueryRow(
		ctx,
		`SELECT count(*), coalesce(max(received_at), '1970-01-01T00:00:00Z'::timestamptz)
		 FROM ais_inbound_requests`,
	).Scan(&snapshot.TotalRequests, &latestReceivedAt); err != nil {
		return nil, err
	}
	if snapshot.TotalRequests > 0 {
		snapshot.LatestReceivedAt = &latestReceivedAt
	}
	if err := s.pool.QueryRow(
		ctx,
		`SELECT count(*) FROM ais_inbound_callbacks WHERE status = 'SKIPPED_DUPLICATE'`,
	).Scan(&snapshot.DuplicateCallbacks); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(
		ctx,
		`WITH latest_evidence AS (
			SELECT DISTINCT ON (request_id) request_id, trace_status
			FROM evidence_traces
			ORDER BY request_id, id DESC
		)
		SELECT count(*) FROM latest_evidence WHERE trace_status = 'PENDING_WORKER'`,
	).Scan(&snapshot.PendingWorkerTraces); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(
		ctx,
		`WITH latest_etr AS (
			SELECT DISTINCT ON (request_id) request_id, status
			FROM etr_candidates
			ORDER BY request_id, id DESC
		)
		SELECT
			count(*) FILTER (WHERE status = 'NOT_READY_FOR_AUTO_SEND'),
			count(*) FILTER (WHERE status = 'SHADOW_BASELINE_CAPTURED')
		FROM latest_etr`,
	).Scan(&snapshot.NotReadyETR, &snapshot.ShadowBaselinePredictionSnapshots); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(ctx, `SELECT count(*) FROM callback_outbox WHERE status = 'DRY_RUN_HELD'`).Scan(&snapshot.OutboxDryRunHeld); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(ctx, `SELECT count(*) FROM callback_dead_letters`).Scan(&snapshot.DeadLetters); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(
		ctx,
		`SELECT
			count(*),
			count(*) FILTER (WHERE validation_status <> 'READY_FOR_LEDGER'),
			count(*) FILTER (WHERE event_type = 'OUTAGE'),
			count(*) FILTER (WHERE event_type = 'RESTORE')
		 FROM ais_truth_ledger`,
	).Scan(&snapshot.TruthObservations, &snapshot.TruthReviewNeeded, &snapshot.TruthOutageEvents, &snapshot.TruthRestoreEvents); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(
		ctx,
		`SELECT
			count(*) FILTER (WHERE semantic_mapping_version = 'alarm_mapping_v2' AND event_type = 'OUTAGE'),
			count(*) FILTER (WHERE semantic_mapping_version = 'alarm_mapping_v2' AND event_type = 'RESTORE'),
			min(created_at) FILTER (WHERE semantic_mapping_version = 'alarm_mapping_v2')
		 FROM ais_truth_ledger`,
	).Scan(&snapshot.V2OutageEvents, &snapshot.V2RestoreEvents, &snapshot.V2ActivationFirstSeenAt); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(
		ctx,
		`SELECT
			count(*) FILTER (WHERE pair_status = 'OPEN'),
			count(*) FILTER (WHERE pair_status = 'OPEN' AND bridge_status = 'METER_STATE_AWAITING_RESTORE'),
			count(*) FILTER (WHERE pair_status = 'REVIEW'),
			count(*) FILTER (WHERE pair_status = 'CLOSED'),
			count(*) FILTER (WHERE pair_status IN ('OPEN', 'REVIEW') OR bridge_status IN ('LEGACY_UNVERIFIED', 'STRICT_DURATION_REVIEW', 'REVIEW_IDENTITY_CONFLICT', 'METER_STATE_DURATION_REVIEW', 'REVIEW_MULTIPLE_OPEN_INTERVALS')),
			count(*) FILTER (WHERE pair_status = 'CLOSED' AND bridge_status = 'METER_STATE_MODEL_READY' AND semantic_mapping_version = 'alarm_mapping_v2' AND restore_at IS NOT NULL AND duration_minutes IS NOT NULL),
			count(*) FILTER (WHERE bridge_status IN ('STRICT_MODEL_READY', 'STRICT_DURATION_REVIEW')),
			count(*) FILTER (WHERE bridge_status IN ('METER_STATE_MODEL_READY', 'METER_STATE_DURATION_REVIEW')),
			count(*) FILTER (WHERE pair_status = 'CLOSED' AND bridge_status = 'METER_STATE_MODEL_READY' AND semantic_mapping_version = 'alarm_mapping_v2' AND restore_at IS NOT NULL AND duration_minutes IS NOT NULL),
			count(*) FILTER (WHERE pair_status = 'OPEN' AND bridge_status = 'METER_STATE_AWAITING_RESTORE' AND semantic_mapping_version = 'alarm_mapping_v2'),
			count(*) FILTER (WHERE pair_status = 'CLOSED' AND bridge_status = 'METER_STATE_MODEL_READY' AND semantic_mapping_version = 'alarm_mapping_v2'),
			count(*) FILTER (WHERE bridge_status = 'REVIEW_PREACTIVATION_PAIR'),
			count(*) FILTER (WHERE bridge_status = 'REVIEW_PREACTIVATION_OPEN'),
			count(*) FILTER (WHERE bridge_status = 'REVIEW_STALE_PREACTIVATION_OPEN'),
			count(*) FILTER (WHERE bridge_status = 'METER_STATE_DURATION_REVIEW' AND semantic_mapping_version = 'alarm_mapping_v2')
		 FROM ais_truth_intervals`,
	).Scan(
		&snapshot.TruthOpenIntervals,
		&snapshot.TruthMeterStateOpenIntervals,
		&snapshot.TruthReviewIntervals,
		&snapshot.TruthClosedIntervals,
		&snapshot.TruthQuarantineIntervals,
		&snapshot.TruthAccuracyEligibleIntervals,
		&snapshot.TruthStrictIdentityIntervals,
		&snapshot.TruthMeterStateIntervals,
		&snapshot.ModelReadyCleanTruthRows,
		&snapshot.V2OpenIntervals,
		&snapshot.V2ModelReadyRows,
		&snapshot.PreactivationPairReview,
		&snapshot.PreactivationOpenReview,
		&snapshot.PreactivationStaleOpenReview,
		&snapshot.V2DurationReview,
	); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(ctx, `
		SELECT count(*) FROM ais_truth_ledger
		WHERE semantic_mapping_version = 'alarm_mapping_v2'
		  AND event_type = 'RESTORE'
		  AND validation_status = 'REVIEW_NO_OPEN_INTERVAL'`).Scan(&snapshot.V2RestoreWithoutOpen); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(ctx, `SELECT count(*) FROM ais_truth_ledger WHERE validation_status <> 'READY_FOR_LEDGER'`).Scan(&snapshot.ModelTruthReviewRows); err != nil {
		return nil, err
	}
	validationRows, err := s.pool.Query(ctx, `SELECT validation_status, count(*) FROM ais_truth_ledger GROUP BY validation_status ORDER BY validation_status`)
	if err != nil {
		return nil, err
	}
	defer validationRows.Close()
	for validationRows.Next() {
		var status string
		var count int64
		if err := validationRows.Scan(&status, &count); err != nil {
			return nil, err
		}
		snapshot.TruthValidationCounts[status] = count
	}
	if err := validationRows.Err(); err != nil {
		return nil, err
	}
	semanticRows, err := s.pool.Query(ctx, `
		SELECT event_type_source || ':' || event_type, count(*)
		FROM ais_truth_ledger
		GROUP BY event_type_source, event_type
		ORDER BY event_type_source, event_type`)
	if err != nil {
		return nil, err
	}
	defer semanticRows.Close()
	for semanticRows.Next() {
		var key string
		var count int64
		if err := semanticRows.Scan(&key, &count); err != nil {
			return nil, err
		}
		snapshot.TruthEventSemanticCounts[key] = count
	}
	if err := semanticRows.Err(); err != nil {
		return nil, err
	}
	if err := s.pool.QueryRow(ctx, `
		SELECT count(*) FROM ais_truth_intervals
		WHERE pair_status = 'OPEN'
		  AND bridge_status = 'METER_STATE_AWAITING_RESTORE'
		  AND outage_at < now() - interval '24 hours'`).Scan(&snapshot.TruthStaleOpenIntervals); err != nil {
		return nil, err
	}
	rows, err := s.pool.Query(ctx, `SELECT status, count(*) FROM ais_inbound_callbacks GROUP BY status ORDER BY status`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var status string
		var count int64
		if err := rows.Scan(&status, &count); err != nil {
			return nil, err
		}
		snapshot.CallbackCounts[status] = count
	}
	return snapshot, rows.Err()
}

func (s *PostgresStore) queryStatuses(ctx context.Context, where string, limit int, args ...any) ([]RequestStatus, error) {
	query := `
	WITH latest_callbacks AS (
		SELECT DISTINCT ON (request_id)
			request_id, payload_json, status, status_code, sent_at
		FROM ais_inbound_callbacks
		ORDER BY request_id, id DESC
	),
	latest_evidence AS (
		SELECT DISTINCT ON (request_id)
			request_id, evidence_json
		FROM evidence_traces
		ORDER BY request_id, id DESC
	),
	latest_etr AS (
		SELECT DISTINCT ON (request_id)
			request_id, status, p50_minutes, q10_minutes, q90_minutes, model_version, generated_at, production_send
		FROM etr_candidates
		ORDER BY request_id, id DESC
	),
	latest_send AS (
		SELECT DISTINCT ON (request_id)
			request_id, policy_mode, effective_mode, eligibility_status, decision, reason, gate_version
		FROM send_decisions
		ORDER BY request_id, id DESC
	),
	latest_outbox AS (
		SELECT DISTINCT ON (request_id)
			request_id, status, transport, attempt_count
		FROM callback_outbox
		ORDER BY request_id, id DESC
	),
	latest_truth AS (
		SELECT DISTINCT ON (request_id)
			request_id, source_event_hash, event_type, event_type_source, semantic_mapping_version, validation_status, site_hash, site_last4
		FROM ais_truth_ledger
		ORDER BY request_id, id DESC
	)
	SELECT r.request_id, r.received_at, r.detected_at, r.detected_at_original,
		r.timestamp_quality, r.meter_hash, r.meter_last4, r.province, r.district, r.subdistrict,
		r.request_json, r.response_json, r.callback_status,
		c.payload_json, c.status, c.status_code, c.sent_at,
		e.evidence_json, coalesce(t.status, ''), t.p50_minutes::float8, t.q10_minutes::float8, t.q90_minutes::float8,
		coalesce(t.model_version, ''), t.generated_at, coalesce(t.production_send, 'blocked'),
		coalesce(s.policy_mode, 'blocked'), coalesce(s.effective_mode, 'blocked'),
		coalesce(s.eligibility_status, 'red_blocked'), coalesce(s.decision, 'blocked'),
		coalesce(s.reason, 'production_send_blocked_by_default'), coalesce(s.gate_version, 'blocked_green_gate'),
		coalesce(o.status, ''), coalesce(o.transport, 'dry_run'), coalesce(o.attempt_count, 0),
		coalesce(tl.event_type, ''), coalesce(tl.event_type_source, ''), coalesce(tl.semantic_mapping_version, 'legacy'), coalesce(tl.validation_status, ''), coalesce(tl.source_event_hash, ''),
		coalesce(tl.site_hash, ''), coalesce(tl.site_last4, '')
	FROM ais_inbound_requests r
	LEFT JOIN latest_callbacks c ON c.request_id = r.request_id
	LEFT JOIN latest_evidence e ON e.request_id = r.request_id
	LEFT JOIN latest_etr t ON t.request_id = r.request_id
	LEFT JOIN latest_send s ON s.request_id = r.request_id
	LEFT JOIN latest_outbox o ON o.request_id = r.request_id
	LEFT JOIN latest_truth tl ON tl.request_id = r.request_id
	` + where + `
	ORDER BY r.received_at DESC
	LIMIT $` + fmt.Sprint(len(args)+1)
	args = append(args, limit)
	rows, err := s.pool.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []RequestStatus{}
	for rows.Next() {
		var item RequestStatus
		if err := rows.Scan(
			&item.RequestID,
			&item.ReceivedAt,
			&item.DetectedAt,
			&item.DetectedAtOriginal,
			&item.TimestampQuality,
			&item.MeterHash,
			&item.MeterLast4,
			&item.Province,
			&item.District,
			&item.Subdistrict,
			&item.RequestJSON,
			&item.ResponseJSON,
			&item.RequestCallback,
			&item.CallbackPayload,
			&item.LatestCallback,
			&item.CallbackStatusCode,
			&item.CallbackSentAt,
			&item.EvidenceJSON,
			&item.ETRStatus,
			&item.ETRP50Minutes,
			&item.ETRQ10Minutes,
			&item.ETRQ90Minutes,
			&item.ETRModelVersion,
			&item.ETRGeneratedAt,
			&item.ProductionSend,
			&item.SendPolicyMode,
			&item.SendEffectiveMode,
			&item.EligibilityStatus,
			&item.SendDecision,
			&item.SendReason,
			&item.SendGateVersion,
			&item.CallbackOutboxStatus,
			&item.CallbackTransport,
			&item.CallbackAttempts,
			&item.TruthEventType,
			&item.TruthEventTypeSource,
			&item.TruthSemanticMappingVersion,
			&item.TruthValidation,
			&item.TruthSourceEventRef,
			&item.TruthSiteHash,
			&item.TruthSiteLast4,
		); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func insertTruthObservation(ctx context.Context, tx pgx.Tx, truth TruthObservation) error {
	_, err := tx.Exec(
		ctx,
		`INSERT INTO ais_truth_ledger (
			request_id, source, source_event_id, source_event_hash, site_hash, site_last4, meter_hash, meter_last4,
			event_type, event_type_source, semantic_mapping_version, detected_at, outage_at, restore_at, timestamp_quality, payload_summary_json,
			validation_status, production_send, created_at
		) VALUES ($1,$2,'',$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
		ON CONFLICT (request_id) DO NOTHING`,
		truth.RequestID,
		truth.Source,
		truth.SourceEventHash,
		truth.SiteHash,
		truth.SiteLast4,
		truth.MeterHash,
		truth.MeterLast4,
		truth.EventType,
		truth.EventTypeSource,
		truth.SemanticMappingVersion,
		truth.DetectedAt,
		truth.OutageAt,
		truth.RestoreAt,
		truth.TimestampQuality,
		truth.PayloadSummaryJSON,
		truth.ValidationStatus,
		truth.ProductionSend,
		truth.CreatedAt,
	)
	return err
}

func upsertTruthInterval(ctx context.Context, tx pgx.Tx, truth TruthObservation) error {
	if truth.ValidationStatus != "READY_FOR_LEDGER" {
		return nil
	}
	if strings.TrimSpace(truth.MeterHash) == "" {
		return updateTruthValidation(ctx, tx, truth.RequestID, "REVIEW_METER_REQUIRED")
	}
	if err := lockMeterState(ctx, tx, truth.MeterHash); err != nil {
		return err
	}
	switch truth.EventType {
	case "OUTAGE":
		if truth.OutageAt == nil {
			return updateTruthValidation(ctx, tx, truth.RequestID, "REVIEW_OUTAGE_TIMESTAMP")
		}
		outageAt := *truth.OutageAt
		existing, err := meterOpenIntervals(ctx, tx, truth.MeterHash, truth.SemanticMappingVersion)
		if err != nil {
			return err
		}
		if len(existing) > 1 {
			if err := markMeterStateConflict(ctx, tx, existing); err != nil {
				return err
			}
			return updateTruthValidation(ctx, tx, truth.RequestID, "REVIEW_MULTIPLE_OPEN_INTERVALS")
		}
		if len(existing) == 1 {
			evidenceJSON, err := json.Marshal(map[string]any{
				"source":                   "go_postgres_meter_state_pairing",
				"reason":                   "repeated_outage_observation_open_interval_unchanged",
				"semantic_mapping_version": truth.SemanticMappingVersion,
				"production_send":          "blocked",
			})
			if err != nil {
				return err
			}
			_, err = tx.Exec(ctx, `UPDATE ais_truth_intervals SET evidence_json=$2, updated_at=now() WHERE id=$1`, existing[0].id, evidenceJSON)
			return err
		}
		evidenceJSON, err := json.Marshal(map[string]any{
			"source":                   "go_postgres_meter_state_pairing",
			"reason":                   "meter_state_outage_waiting_for_restore",
			"semantic_mapping_version": truth.SemanticMappingVersion,
			"production_send":          "blocked",
		})
		if err != nil {
			return err
		}
		_, err = tx.Exec(
			ctx,
			`INSERT INTO ais_truth_intervals (
				interval_id, source, outage_request_id, correlation_hash, meter_hash, meter_last4, site_hash, site_last4,
				outage_at, pair_status, bridge_status, semantic_mapping_version, evidence_json, production_send
			) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'OPEN','METER_STATE_AWAITING_RESTORE',$10,$11,'blocked')
			ON CONFLICT (interval_id) DO NOTHING`,
			truthIntervalID(truth, outageAt),
			blankDefault(truth.Source, "AIS"),
			truth.RequestID,
			truth.SourceEventHash,
			truth.MeterHash,
			truth.MeterLast4,
			truth.SiteHash,
			truth.SiteLast4,
			outageAt,
			truth.SemanticMappingVersion,
			evidenceJSON,
		)
		return err
	case "RESTORE":
		if truth.RestoreAt == nil {
			return updateTruthValidation(ctx, tx, truth.RequestID, "REVIEW_RESTORE_TIMESTAMP")
		}
		restoreAt := *truth.RestoreAt
		matches, err := meterOpenIntervals(ctx, tx, truth.MeterHash, truth.SemanticMappingVersion)
		if err != nil {
			return err
		}
		outageAt := time.Time{}
		if len(matches) > 0 {
			outageAt = matches[0].outageAt
		}
		outcome := strictRestoreOutcome(len(matches), outageAt, restoreAt)
		if outcome.validationStatus == "REVIEW_NO_OPEN_INTERVAL" {
			return updateTruthValidation(ctx, tx, truth.RequestID, outcome.validationStatus)
		}
		if outcome.validationStatus == "REVIEW_MULTIPLE_OPEN_INTERVALS" {
			if err := markMeterStateConflict(ctx, tx, matches); err != nil {
				return err
			}
			return updateTruthValidation(ctx, tx, truth.RequestID, outcome.validationStatus)
		}
		match := matches[0]
		if outcome.validationStatus == "REVIEW_RESTORE_BEFORE_OUTAGE" {
			return updateTruthValidation(ctx, tx, truth.RequestID, outcome.validationStatus)
		}
		evidenceJSON, err := json.Marshal(map[string]any{
			"source":                   "go_postgres_meter_state_pairing",
			"reason":                   outcome.reason,
			"semantic_mapping_version": truth.SemanticMappingVersion,
			"production_send":          "blocked",
		})
		if err != nil {
			return err
		}
		_, err = tx.Exec(
			ctx,
			`UPDATE ais_truth_intervals
			 SET restore_request_id = $2,
				 restore_at = $3,
				 duration_minutes = round($4::numeric, 3),
				 pair_status = $5,
				 bridge_status = $6,
				 evidence_json = $7,
				 updated_at = now()
			 WHERE id = $1`,
			match.id,
			truth.RequestID,
			restoreAt,
			outcome.durationMinutes,
			outcome.pairStatus,
			outcome.bridgeStatus,
			evidenceJSON,
		)
		if err != nil {
			return err
		}
		return updateTruthValidation(ctx, tx, truth.RequestID, outcome.validationStatus)
	default:
		return nil
	}
}

type openTruthInterval struct {
	id       int64
	outageAt time.Time
}

type strictRestoreResult struct {
	durationMinutes  float64
	pairStatus       string
	bridgeStatus     string
	validationStatus string
	reason           string
}

func strictRestoreOutcome(openCount int, outageAt, restoreAt time.Time) strictRestoreResult {
	if openCount == 0 {
		return strictRestoreResult{validationStatus: "REVIEW_NO_OPEN_INTERVAL"}
	}
	if openCount > 1 {
		return strictRestoreResult{validationStatus: "REVIEW_MULTIPLE_OPEN_INTERVALS"}
	}
	if !restoreAt.After(outageAt) {
		return strictRestoreResult{validationStatus: "REVIEW_RESTORE_BEFORE_OUTAGE"}
	}
	durationMinutes := restoreAt.Sub(outageAt).Minutes()
	if !strictModelDuration(durationMinutes) {
		return strictRestoreResult{
			durationMinutes:  durationMinutes,
			pairStatus:       "REVIEW",
			bridgeStatus:     "METER_STATE_DURATION_REVIEW",
			validationStatus: "REVIEW_DURATION_OUT_OF_RANGE",
			reason:           "meter_state_pair_duration_out_of_range",
		}
	}
	return strictRestoreResult{
		durationMinutes:  durationMinutes,
		pairStatus:       "CLOSED",
		bridgeStatus:     "METER_STATE_MODEL_READY",
		validationStatus: "READY_FOR_LEDGER",
		reason:           "meter_state_pair_model_ready",
	}
}

func meterOpenIntervals(ctx context.Context, tx pgx.Tx, meterHash, semanticMappingVersion string) ([]openTruthInterval, error) {
	rows, err := tx.Query(ctx, `
		SELECT id, outage_at
		FROM ais_truth_intervals
		WHERE pair_status = 'OPEN'
		  AND bridge_status = 'METER_STATE_AWAITING_RESTORE'
		  AND production_send = 'blocked'
		  AND meter_hash = $1
		  AND semantic_mapping_version = $2
		ORDER BY outage_at ASC, id ASC
		FOR UPDATE`, meterHash, semanticMappingVersion)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []openTruthInterval{}
	for rows.Next() {
		var item openTruthInterval
		if err := rows.Scan(&item.id, &item.outageAt); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
}

func lockMeterState(ctx context.Context, tx pgx.Tx, meterHash string) error {
	_, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, "meter-state|"+meterHash)
	return err
}

func markMeterStateConflict(ctx context.Context, tx pgx.Tx, intervals []openTruthInterval) error {
	ids := make([]int64, 0, len(intervals))
	for _, interval := range intervals {
		ids = append(ids, interval.id)
	}
	evidenceJSON, err := json.Marshal(map[string]any{
		"source":          "go_postgres_meter_state_pairing",
		"reason":          "meter_state_multiple_open_intervals",
		"production_send": "blocked",
	})
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `
		UPDATE ais_truth_intervals
		SET pair_status = 'REVIEW', bridge_status = 'REVIEW_MULTIPLE_OPEN_INTERVALS', evidence_json = $2, updated_at = now()
		WHERE id = ANY($1)`, ids, evidenceJSON)
	return err
}

func updateTruthValidation(ctx context.Context, tx pgx.Tx, requestID, validationStatus string) error {
	_, err := tx.Exec(ctx, `UPDATE ais_truth_ledger SET validation_status = $2 WHERE request_id = $1`, requestID, validationStatus)
	return err
}

func truthIntervalID(truth TruthObservation, outageAt time.Time) string {
	basis := truth.MeterHash + "|" + truth.RequestID + "|" + outageAt.UTC().Format(time.RFC3339)
	sum := sha256.Sum256([]byte(basis))
	return "ais-" + hex.EncodeToString(sum[:])[:20]
}

func truthCorrelationHash(truth TruthObservation) string {
	return truth.SourceEventHash
}

func strictModelDuration(durationMinutes float64) bool {
	return durationMinutes > 5 && durationMinutes <= 1440
}

func truthPairKey(truth TruthObservation) string {
	return truth.MeterHash
}

func insertCallback(ctx context.Context, tx pgx.Tx, callback Callback) error {
	_, err := tx.Exec(
		ctx,
		`INSERT INTO ais_inbound_callbacks (request_id, callback_url, mode, payload_json, status, status_code, response_text, sent_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
		callback.RequestID,
		nullIfEmpty(callback.CallbackURL),
		callback.Mode,
		callback.PayloadJSON,
		callback.Status,
		callback.StatusCode,
		nullIfEmpty(callback.ResponseText),
		callback.SentAt,
	)
	return err
}

func insertEvidence(ctx context.Context, tx pgx.Tx, evidence EvidenceTrace) error {
	_, err := tx.Exec(
		ctx,
		`INSERT INTO evidence_traces (request_id, trace_status, match_found, match_level, confidence, evidence_json, production_send, generated_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
		evidence.RequestID,
		evidence.TraceStatus,
		evidence.MatchFound,
		evidence.MatchLevel,
		evidence.Confidence,
		evidence.EvidenceJSON,
		evidence.ProductionSend,
		evidence.GeneratedAt,
	)
	return err
}

func insertETR(ctx context.Context, tx pgx.Tx, etr ETRCandidate) error {
	_, err := tx.Exec(
		ctx,
		`INSERT INTO etr_candidates (request_id, status, p50_minutes, q10_minutes, q90_minutes, risk_level, model_version, production_gate, production_send, generated_at)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
		etr.RequestID,
		etr.Status,
		etr.P50Minutes,
		etr.Q10Minutes,
		etr.Q90Minutes,
		etr.RiskLevel,
		etr.ModelVersion,
		etr.ProductionGate,
		etr.ProductionSend,
		etr.GeneratedAt,
	)
	return err
}

func insertSendDecision(ctx context.Context, tx pgx.Tx, decision SendDecision) (int64, error) {
	var id int64
	err := tx.QueryRow(
		ctx,
		`INSERT INTO send_decisions (
			request_id, policy_mode, effective_mode, eligibility_status, decision, reason,
			gate_version, source, operator_actor, production_send, decided_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
		RETURNING id`,
		decision.RequestID,
		decision.PolicyMode,
		decision.EffectiveMode,
		decision.EligibilityStatus,
		decision.Decision,
		decision.Reason,
		decision.GateVersion,
		decision.Source,
		decision.OperatorActor,
		decision.ProductionSend,
		decision.DecidedAt,
	).Scan(&id)
	return id, err
}

func insertCallbackOutbox(ctx context.Context, tx pgx.Tx, decisionID int64, outbox CallbackOutbox) error {
	_, err := tx.Exec(
		ctx,
		`INSERT INTO callback_outbox (
			request_id, decision_id, payload_hash, payload_json, transport, status,
			attempt_count, max_attempts, last_error, production_send, created_at, updated_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
		ON CONFLICT (request_id, payload_hash) DO NOTHING`,
		callbackOutboxInsertArgs(decisionID, outbox)...,
	)
	return err
}

func callbackOutboxInsertArgs(decisionID int64, outbox CallbackOutbox) []any {
	return []any{
		outbox.RequestID,
		decisionID,
		outbox.PayloadHash,
		outbox.PayloadJSON,
		outbox.Transport,
		outbox.Status,
		outbox.AttemptCount,
		outbox.MaxAttempts,
		outbox.LastError,
		outbox.ProductionSend,
		outbox.CreatedAt,
		outbox.UpdatedAt,
	}
}

func nullIfEmpty(value string) any {
	if value == "" {
		return nil
	}
	return value
}

func blankDefault(value string, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func IsUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}
