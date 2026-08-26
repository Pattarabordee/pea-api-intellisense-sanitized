package correlation

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"pea-api-intellisense/apps/api-go/internal/storage"
)

type memoryWorkerStore struct {
	jobs          map[string]storage.CorrelationJob
	snapshots     map[string]storage.CorrelationReportSnapshot
	failSnapshots bool
	relationships []storage.CorrelationRelationship
	clusters      map[string]storage.CorrelationCluster
	revisions     map[string][]storage.CorrelationClusterRevision
	memberships   []storage.CorrelationMembershipRevision
	lineage       []storage.CorrelationClusterLineage
}

func newMemoryWorkerStore() *memoryWorkerStore {
	return &memoryWorkerStore{
		jobs: map[string]storage.CorrelationJob{}, snapshots: map[string]storage.CorrelationReportSnapshot{},
		clusters: map[string]storage.CorrelationCluster{}, revisions: map[string][]storage.CorrelationClusterRevision{},
	}
}

func (m *memoryWorkerStore) ClaimCorrelationJob(_ context.Context, worker string, _ time.Duration) (*storage.CorrelationJob, error) {
	for id, job := range m.jobs {
		if job.State != "PENDING" && job.State != "RETRYING" {
			continue
		}
		if !job.AvailableAt.IsZero() && job.AvailableAt.After(time.Now().Add(time.Second)) {
			continue
		}
		job.State = "PROCESSING"
		job.AttemptCount++
		job.ClaimedBy = worker
		m.jobs[id] = job
		copy := job
		return &copy, nil
	}
	return nil, storage.ErrNotFound
}

func (m *memoryWorkerStore) CompleteCorrelationJob(_ context.Context, id, worker string) error {
	job := m.jobs[id]
	if job.State != "PROCESSING" || job.ClaimedBy != worker {
		return errors.New("lost lease")
	}
	job.State = "SUCCEEDED"
	job.ClaimedBy = ""
	m.jobs[id] = job
	return nil
}

func (m *memoryWorkerStore) RetryOrFailCorrelationJob(_ context.Context, job storage.CorrelationJob, worker, class string, next time.Time) (string, error) {
	current := m.jobs[job.JobID]
	if current.State != "PROCESSING" || current.ClaimedBy != worker {
		return "", errors.New("lost lease")
	}
	state := "RETRYING"
	if current.AttemptCount >= current.MaxAttempts {
		state = "FAILED"
	}
	current.State = state
	current.LastErrorClass = class
	current.AvailableAt = time.Now().Add(-time.Millisecond)
	current.ClaimedBy = ""
	m.jobs[job.JobID] = current
	return state, nil
}

func (m *memoryWorkerStore) GetCorrelationReportSnapshot(_ context.Context, id string) (*storage.CorrelationReportSnapshot, error) {
	if m.failSnapshots {
		return nil, errors.New("synthetic snapshot failure")
	}
	item, ok := m.snapshots[id]
	if !ok {
		return nil, storage.ErrNotFound
	}
	copy := item
	return &copy, nil
}

func (m *memoryWorkerStore) ListCorrelationReportSnapshots(_ context.Context, _ int) ([]storage.CorrelationReportSnapshot, error) {
	if m.failSnapshots {
		return nil, errors.New("synthetic snapshot failure")
	}
	out := make([]storage.CorrelationReportSnapshot, 0, len(m.snapshots))
	for _, item := range m.snapshots {
		out = append(out, item)
	}
	return out, nil
}

func (m *memoryWorkerStore) ListLatestCorrelationMemberships(context.Context) ([]storage.CorrelationMembershipRevision, error) {
	latest := map[string]storage.CorrelationMembershipRevision{}
	for _, item := range m.memberships {
		if item.MembershipRevision >= latest[item.ReportID].MembershipRevision {
			latest[item.ReportID] = item
		}
	}
	out := make([]storage.CorrelationMembershipRevision, 0, len(latest))
	for _, item := range latest {
		out = append(out, item)
	}
	return out, nil
}

func (m *memoryWorkerStore) GetLatestCorrelationClusterRevision(_ context.Context, id string) (*storage.CorrelationClusterRevision, error) {
	items := m.revisions[id]
	if len(items) == 0 {
		return nil, storage.ErrNotFound
	}
	copy := items[len(items)-1]
	return &copy, nil
}

func (m *memoryWorkerStore) InsertCorrelationRelationship(_ context.Context, item storage.CorrelationRelationship) (int, bool, error) {
	for i, existing := range m.relationships {
		if existing.DecisionHash == item.DecisionHash {
			return i + 1, true, nil
		}
	}
	item.Revision = 1
	m.relationships = append(m.relationships, item)
	return 1, false, nil
}

func (m *memoryWorkerStore) InsertCorrelationCluster(_ context.Context, item storage.CorrelationCluster) (bool, error) {
	_, exists := m.clusters[item.ClusterID]
	m.clusters[item.ClusterID] = item
	return exists, nil
}

func (m *memoryWorkerStore) InsertCorrelationClusterRevision(_ context.Context, item storage.CorrelationClusterRevision) (int, bool, error) {
	for _, items := range m.revisions {
		for _, existing := range items {
			if existing.DecisionHash == item.DecisionHash {
				return existing.Revision, true, nil
			}
		}
	}
	current := len(m.revisions[item.ClusterID])
	if item.ExpectedRevision != nil && *item.ExpectedRevision != current {
		return 0, false, storage.ErrCorrelationRevisionConflict
	}
	item.Revision = current + 1
	m.revisions[item.ClusterID] = append(m.revisions[item.ClusterID], item)
	return item.Revision, false, nil
}

func (m *memoryWorkerStore) InsertCorrelationMembershipRevision(_ context.Context, item storage.CorrelationMembershipRevision) (int, bool, error) {
	for _, existing := range m.memberships {
		if existing.DecisionHash == item.DecisionHash {
			return existing.MembershipRevision, true, nil
		}
	}
	next := 1
	for _, existing := range m.memberships {
		if existing.ReportID == item.ReportID && existing.MembershipRevision >= next {
			next = existing.MembershipRevision + 1
		}
	}
	item.MembershipRevision = next
	m.memberships = append(m.memberships, item)
	return next, false, nil
}

func (m *memoryWorkerStore) InsertCorrelationClusterLineage(_ context.Context, item storage.CorrelationClusterLineage) (bool, error) {
	m.lineage = append(m.lineage, item)
	return false, nil
}

func workerSnapshot(id, ticket, feeder, tx string, when time.Time) storage.CorrelationReportSnapshot {
	location, _ := json.Marshal(map[string]any{"province": "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", "district": "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", "subdistrict": "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", "village": "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¹Ã¢â‚¬Â°ÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã¢â€žÂ¢ÃƒÂ Ã‚Â¸Ã¢â‚¬ÂÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚Â«ÃƒÂ Ã‚Â¸Ã‚Â¡ÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â¢ÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ ÃƒÂ Ã‚Â¸Ã‚Â«ÃƒÂ Ã‚Â¸Ã‚Â¡ÃƒÂ Ã‚Â¸Ã‚Â¹ÃƒÂ Ã‚Â¹Ã‹â€  7"})
	topology, _ := json.Marshal(map[string]any{"feeder_id": feeder, "transformer_ids": []string{tx}, "upstream_protection_ids": []string{}, "authoritative": true})
	freshness, _ := json.Marshal(map[string]any{"topology": FreshnessUnknown})
	return storage.CorrelationReportSnapshot{
		Report:   storage.CorrelationReport{ReportID: id, TicketID: ticket, SourceSystem: "n8n-pea-buengkan", SourceChannel: "chat", SessionRefHash: "session-" + id, OccurredAt: when, PlannedOutageState: PlannedNoMatch},
		Evidence: storage.CorrelationEvidenceRevision{ReportID: id, Revision: 1, EvidenceHash: "evidence-" + id, TopologyJSON: topology, LocationJSON: location, FreshnessJSON: freshness, PlannedOutageState: PlannedNoMatch},
	}
}

func TestWorkerCompletesDurableJobAndCreatesSuspectedCluster(t *testing.T) {
	store := newMemoryWorkerStore()
	now := time.Now().UTC()
	store.snapshots["r1"] = workerSnapshot("r1", "PEA-20260826-000001", "BUA03", "TX-A", now)
	store.snapshots["r2"] = workerSnapshot("r2", "PEA-20260826-000002", "BUA03", "TX-B", now.Add(5*time.Minute))
	store.jobs["j2"] = storage.CorrelationJob{JobID: "j2", ReportID: "r2", TriggerEvidenceRevision: 1, State: "PENDING", MaxAttempts: 3, AvailableAt: now.Add(-time.Second)}

	worker := NewWorker(store, WorkerConfig{WorkerID: "test-worker", EngineConfig: DefaultShadowConfig(), SnapshotLimit: 100})
	worked, err := worker.RunOnce(context.Background())
	if err != nil || !worked {
		t.Fatalf("worker failed: worked=%v err=%v", worked, err)
	}
	if store.jobs["j2"].State != "SUCCEEDED" {
		t.Fatalf("job should succeed, got %#v", store.jobs["j2"])
	}
	if len(store.relationships) != 1 || store.relationships[0].RelationshipState != "SUSPECTED" {
		t.Fatalf("expected one suspected relationship, got %#v", store.relationships)
	}
	if len(store.clusters) != 1 {
		t.Fatalf("expected one suspected cluster, got %d", len(store.clusters))
	}
	active := 0
	for _, item := range store.memberships {
		if item.MembershipState == "ACTIVE" {
			active++
		}
	}
	if active != 2 {
		t.Fatalf("expected two active memberships, got %#v", store.memberships)
	}
	for _, revisions := range store.revisions {
		if revisions[len(revisions)-1].CorrelationStatus != "SUSPECTED_RELATED" || revisions[len(revisions)-1].ConfidenceLevel != ConfidenceMedium {
			t.Fatalf("unexpected cluster revision: %#v", revisions)
		}
	}
}

func TestWorkerUsesBoundedRetryThenFails(t *testing.T) {
	store := newMemoryWorkerStore()
	now := time.Now().UTC()
	store.snapshots["r1"] = workerSnapshot("r1", "PEA-20260826-000003", "BUA03", "TX-A", now)
	store.jobs["j1"] = storage.CorrelationJob{JobID: "j1", ReportID: "r1", TriggerEvidenceRevision: 1, State: "PENDING", MaxAttempts: 2, AvailableAt: now.Add(-time.Second)}
	store.failSnapshots = true
	worker := NewWorker(store, WorkerConfig{WorkerID: "test-worker", EngineConfig: DefaultShadowConfig()})

	if worked, err := worker.RunOnce(context.Background()); err != nil || !worked {
		t.Fatalf("first failed attempt should be handled as retry: worked=%v err=%v", worked, err)
	}
	if got := store.jobs["j1"].State; got != "RETRYING" {
		t.Fatalf("expected RETRYING after first failure, got %s", got)
	}
	if worked, err := worker.RunOnce(context.Background()); err != nil || !worked {
		t.Fatalf("second failed attempt should be handled: worked=%v err=%v", worked, err)
	}
	if got := store.jobs["j1"].State; got != "FAILED" {
		t.Fatalf("expected FAILED after max attempts, got %s", got)
	}
	if store.jobs["j1"].AttemptCount != 2 {
		t.Fatalf("bounded attempts violated: %#v", store.jobs["j1"])
	}
}

func (m *memoryWorkerStore) AcquireCorrelationScopeLocks(context.Context, []string) (func(), error) {
	return func() {}, nil
}

func TestCandidateScopeUsesTopologyBeforeAdminFallback(t *testing.T) {
	now := time.Now().UTC()
	current := ReportEvidence{ReportID: "r1", OccurredAt: now, Province: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", District: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", Subdistrict: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", FeederID: "BUA03"}
	sameFeeder := ReportEvidence{ReportID: "r2", OccurredAt: now, Province: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", District: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", Subdistrict: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", FeederID: "BUA03"}
	differentFeederSameAdmin := ReportEvidence{ReportID: "r3", OccurredAt: now, Province: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", District: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", Subdistrict: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", FeederID: "BUA04"}
	fallbackNoTopology := ReportEvidence{ReportID: "r4", OccurredAt: now, Province: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", District: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬", Subdistrict: "ÃƒÂ Ã‚Â¸Ã…Â¡ÃƒÂ Ã‚Â¸Ã‚Â¶ÃƒÂ Ã‚Â¸Ã¢â‚¬Â¡ÃƒÂ Ã‚Â¸Ã‚ÂÃƒÂ Ã‚Â¸Ã‚Â²ÃƒÂ Ã‚Â¸Ã‚Â¬"}
	got := candidateScopeReports(current, []ReportEvidence{current, sameFeeder, differentFeederSameAdmin, fallbackNoTopology})
	seen := map[string]bool{}
	for _, report := range got {
		seen[report.ReportID] = true
	}
	if !seen["r1"] || !seen["r2"] || !seen["r4"] {
		t.Fatalf("expected current, same feeder, and admin fallback candidates: %#v", seen)
	}
	if seen["r3"] {
		t.Fatalf("known different feeder must not re-enter through admin fallback: %#v", seen)
	}
}

func TestCandidateScopeAllowsCommonUpstreamAcrossFeeders(t *testing.T) {
	now := time.Now().UTC()
	a := ReportEvidence{ReportID: "r1", OccurredAt: now, FeederID: "BUA03", UpstreamProtectionIDs: []string{"RC-01"}}
	b := ReportEvidence{ReportID: "r2", OccurredAt: now, FeederID: "BUA04", UpstreamProtectionIDs: []string{"RC-01"}}
	got := candidateScopeReports(a, []ReportEvidence{a, b})
	if len(got) != 2 {
		t.Fatalf("common upstream protection must keep cross-feeder report in candidate scope: %#v", got)
	}
	keys := correlationScopeKeys(a)
	joined := strings.Join(keys, ",")
	if !strings.Contains(joined, "upstream:RC-01") || !strings.Contains(joined, "feeder:BUA03") {
		t.Fatalf("expected feeder and upstream scoped locks, got %#v", keys)
	}
}
