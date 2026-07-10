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
	InsertInbound(ctx context.Context, request InboundRequest, truth TruthObservation, callback Callback, evidence EvidenceTrace, etr ETRCandidate, send SendDecision, outbox CallbackOutbox) (duplicate bool, err error)
	InsertCallback(ctx context.Context, callback Callback) error
	GetStatus(ctx context.Context, requestID string) (*RequestStatus, error)
	ListStatuses(ctx context.Context, limit int) ([]RequestStatus, error)
	ListTruthIntervals(ctx context.Context, status string, limit int) ([]TruthInterval, error)
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

type TruthObservation struct {
	RequestID          string
	Source            string
	SourceEventID     string
	SourceEventHash   string
	SiteHash          string
	SiteLast4         string
	MeterHash         string
	MeterLast4        string
	EventType         string
	EventTypeSource   string
	DetectedAt        time.Time
	OutageAt          *time.Time
	RestoreAt         *time.Time
	TimestampQuality  json.RawMessage
	PayloadSummaryJSON json.RawMessage
	ValidationStatus  string
	ProductionSend    string
	CreatedAt         time.Time
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

type SendDecision struct {
	RequestID          string
	PolicyMode         string
	EffectiveMode      string
	EligibilityStatus  string
	Decision           string
	Reason             string
	GateVersion        string
	Source             string
	OperatorActor      string
	ProductionSend     string
	DecidedAt          time.Time
}

type CallbackOutbox struct {
	RequestID      string
	PayloadHash    string
	PayloadJSON    json.RawMessage
	Transport      string
	Status         string
	AttemptCount   int
	MaxAttempts    int
	LastError      string
	ProductionSend string
	CreatedAt      time.Time
	UpdatedAt      time.Time
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
	SendPolicyMode     string
	SendEffectiveMode  string
	EligibilityStatus  string
	SendDecision       string
	SendReason         string
	SendGateVersion    string
	CallbackOutboxStatus string
	CallbackTransport string
	CallbackAttempts  int
	TruthEventType       string
	TruthValidation      string
	TruthSourceEventRef  string
	TruthEventTypeSource string
	TruthSiteHash        string
	TruthSiteLast4       string
}

type TruthInterval struct {
	IntervalID       string
	Source           string
	OutageRequestID  string
	RestoreRequestID string
	CorrelationHash  string
	MeterHash        string
	MeterLast4       string
	SiteHash         string
	SiteLast4        string
	OutageAt         time.Time
	RestoreAt        *time.Time
	DurationMinutes  *float64
	PairStatus       string
	BridgeStatus     string
	EvidenceJSON     json.RawMessage
	ProductionSend   string
	CreatedAt        time.Time
	UpdatedAt        time.Time
}

type MetricsSnapshot struct {
	TotalRequests                 int64
	DuplicateCallbacks            int64
	PendingWorkerTraces           int64
	NotReadyETR                   int64
	OutboxDryRunHeld              int64
	DeadLetters                   int64
	TruthObservations             int64
	TruthReviewNeeded             int64
	TruthOutageEvents             int64
	TruthRestoreEvents            int64
	TruthOpenIntervals            int64
	TruthReviewIntervals          int64
	TruthClosedIntervals          int64
	TruthQuarantineIntervals      int64
	TruthAccuracyEligibleIntervals int64
	TruthStrictIdentityIntervals   int64
	TruthMeterStateIntervals       int64
	ModelReadyCleanTruthRows       int64
	ModelTruthReviewRows           int64
	TruthStaleOpenIntervals        int64
	CallbackCounts                map[string]int64
	TruthValidationCounts         map[string]int64
	TruthEventSemanticCounts      map[string]int64
	LatestReceivedAt              *time.Time
}
