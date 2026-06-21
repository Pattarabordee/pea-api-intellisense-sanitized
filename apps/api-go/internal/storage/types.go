package storage

import (
	"context"
	"encoding/json"
	"errors"
	"time"
)

var ErrNotFound = errors.New("record not found")

type Store interface {
	Init(ctx context.Context) error
	Health(ctx context.Context) error
	InsertInbound(ctx context.Context, request InboundRequest, callback Callback, evidence EvidenceTrace, etr ETRCandidate) (duplicate bool, err error)
	InsertCallback(ctx context.Context, callback Callback) error
	GetStatus(ctx context.Context, requestID string) (*RequestStatus, error)
	ListStatuses(ctx context.Context, limit int) ([]RequestStatus, error)
	Metrics(ctx context.Context) (*MetricsSnapshot, error)
}

type InboundRequest struct {
	RequestID          string
	ReceivedAt         time.Time
	MeterHash          string
	MeterLast4         string
	DetectedAt         time.Time
	DetectedAtOriginal string
	TimestampQuality   json.RawMessage
	Province           string
	District           string
	Subdistrict        string
	RequestJSON        json.RawMessage
	ResponseJSON       json.RawMessage
	CallbackStatus     string
}

type Callback struct {
	RequestID    string
	CallbackURL  string
	Mode         string
	PayloadJSON  json.RawMessage
	Status       string
	StatusCode   *int
	ResponseText string
	SentAt       time.Time
}

type EvidenceTrace struct {
	RequestID       string
	TraceStatus     string
	MatchFound      bool
	MatchLevel      string
	Confidence      string
	EvidenceJSON    json.RawMessage
	ProductionSend  string
	GeneratedAt     time.Time
}

type ETRCandidate struct {
	RequestID      string
	Status         string
	P50Minutes     *float64
	Q10Minutes     *float64
	Q90Minutes     *float64
	RiskLevel      string
	ModelVersion   string
	ProductionGate string
	ProductionSend string
	GeneratedAt    time.Time
}

type RequestStatus struct {
	RequestID          string
	ReceivedAt         time.Time
	DetectedAt         time.Time
	DetectedAtOriginal string
	TimestampQuality   json.RawMessage
	MeterHash          string
	MeterLast4         string
	Province           string
	District           string
	Subdistrict        string
	RequestJSON        json.RawMessage
	ResponseJSON       json.RawMessage
	RequestCallback    string
	CallbackPayload    json.RawMessage
	LatestCallback     string
	CallbackStatusCode *int
	CallbackSentAt     *time.Time
	EvidenceJSON       json.RawMessage
	ETRStatus          string
	ProductionSend     string
}

type MetricsSnapshot struct {
	TotalRequests       int64
	DuplicateCallbacks  int64
	PendingWorkerTraces int64
	NotReadyETR         int64
	CallbackCounts      map[string]int64
	LatestReceivedAt    *time.Time
}
