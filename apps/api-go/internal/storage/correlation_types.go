package storage

import (
	"encoding/json"
	"time"
)

// CorrelationReport is the durable, privacy-safe identity for one accepted
// chatbot/outage report. It intentionally excludes customer name/phone/raw text.
type CorrelationReport struct {
	ReportID               string
	TicketID               string
	SourceSystem           string
	SourceChannel          string
	SourceEventHash        string
	SessionRefHash         string
	OccurredAt             time.Time
	NormalizedLocationJSON json.RawMessage
	CoreRequestID          string
	PlannedOutageState     string
	Mode                   string
	ProductionSend         string
	CreatedAt              time.Time
}

type CorrelationEvidenceRevision struct {
	ReportID           string
	Revision           int
	EvidenceHash       string
	TopologyJSON       json.RawMessage
	LocationJSON       json.RawMessage
	FreshnessJSON      json.RawMessage
	PlannedOutageState string
	EvidenceQuality    string
	RecordedAt         time.Time
	SourceVersion      string
}

type CorrelationRelationship struct {
	ReportAID         string
	ReportBID         string
	Revision          int
	DecisionHash      string
	ConfidenceScore   float64
	ConfidenceLevel   string
	HardVeto          bool
	RelationshipState string
	EvidenceJSON      json.RawMessage
	EngineVersion     string
	CreatedAt         time.Time
}

type CorrelationCluster struct {
	ClusterID            string
	CreatedAt            time.Time
	CreatedEngineVersion string
	Mode                 string
}

type CorrelationClusterRevision struct {
	ClusterID              string
	Revision               int
	DecisionHash           string
	LifecycleState         string
	CorrelationStatus      string
	ConfidenceScore        float64
	ConfidenceLevel        string
	RawReportCount         int
	UniqueReporterCount    int
	TopologyHypothesisJSON json.RawMessage
	EvidenceSummaryJSON    json.RawMessage
	EngineVersion          string
	CreatedAt              time.Time
}

type CorrelationMembershipRevision struct {
	ReportID           string
	ClusterID          string
	MembershipRevision int
	MembershipState    string
	AssignmentReason   string
	ConfidenceScore    float64
	ConfidenceLevel    string
	EngineVersion      string
	DecisionHash       string
	CreatedAt          time.Time
}

type CorrelationClusterLineage struct {
	ParentClusterID string
	ChildClusterID  string
	RelationType    string
	ParentRevision  int
	ChildRevision   int
	Reason          string
	EngineVersion   string
	CreatedAt       time.Time
}
