package storage

import (
	"context"
	"embed"
	"errors"
	"fmt"
	"sort"
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

func (s *PostgresStore) InsertInbound(ctx context.Context, request InboundRequest, callback Callback, evidence EvidenceTrace, etr ETRCandidate) (bool, error) {
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
	if err := insertCallback(ctx, tx, callback); err != nil {
		return false, err
	}
	if err := insertEvidence(ctx, tx, evidence); err != nil {
		return false, err
	}
	if err := insertETR(ctx, tx, etr); err != nil {
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

func (s *PostgresStore) Metrics(ctx context.Context) (*MetricsSnapshot, error) {
	snapshot := &MetricsSnapshot{CallbackCounts: map[string]int64{}}
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
		SELECT count(*) FROM latest_etr WHERE status = 'NOT_READY_FOR_AUTO_SEND'`,
	).Scan(&snapshot.NotReadyETR); err != nil {
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
			request_id, status, production_send
		FROM etr_candidates
		ORDER BY request_id, id DESC
	)
	SELECT r.request_id, r.received_at, r.detected_at, r.detected_at_original,
		r.timestamp_quality, r.meter_hash, r.meter_last4, r.province, r.district, r.subdistrict,
		r.request_json, r.response_json, r.callback_status,
		c.payload_json, c.status, c.status_code, c.sent_at,
		e.evidence_json, coalesce(t.status, ''), coalesce(t.production_send, 'blocked')
	FROM ais_inbound_requests r
	LEFT JOIN latest_callbacks c ON c.request_id = r.request_id
	LEFT JOIN latest_evidence e ON e.request_id = r.request_id
	LEFT JOIN latest_etr t ON t.request_id = r.request_id
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
			&item.ProductionSend,
		); err != nil {
			return nil, err
		}
		result = append(result, item)
	}
	return result, rows.Err()
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

func nullIfEmpty(value string) any {
	if value == "" {
		return nil
	}
	return value
}

func IsUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}
