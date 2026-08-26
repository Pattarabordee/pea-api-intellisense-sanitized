package correlation

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"strings"
	"time"

	"pea-api-intellisense/apps/api-go/internal/storage"
)

type WorkerStore interface {
	ClaimCorrelationJob(context.Context, string, time.Duration) (*storage.CorrelationJob, error)
	AcquireCorrelationScopeLocks(context.Context, []string) (func(), error)
	CompleteCorrelationJob(context.Context, string, string) error
	RetryOrFailCorrelationJob(context.Context, storage.CorrelationJob, string, string, time.Time) (string, error)
	GetCorrelationReportSnapshot(context.Context, string) (*storage.CorrelationReportSnapshot, error)
	ListCorrelationReportSnapshots(context.Context, int) ([]storage.CorrelationReportSnapshot, error)
	ListLatestCorrelationMemberships(context.Context) ([]storage.CorrelationMembershipRevision, error)
	GetLatestCorrelationClusterRevision(context.Context, string) (*storage.CorrelationClusterRevision, error)
	InsertCorrelationRelationship(context.Context, storage.CorrelationRelationship) (int, bool, error)
	InsertCorrelationCluster(context.Context, storage.CorrelationCluster) (bool, error)
	InsertCorrelationClusterRevision(context.Context, storage.CorrelationClusterRevision) (int, bool, error)
	InsertCorrelationMembershipRevision(context.Context, storage.CorrelationMembershipRevision) (int, bool, error)
	InsertCorrelationClusterLineage(context.Context, storage.CorrelationClusterLineage) (bool, error)
}

type WorkerConfig struct {
	WorkerID      string
	PollInterval  time.Duration
	LeaseDuration time.Duration
	SnapshotLimit int
	EngineConfig  Config
	Logger        *slog.Logger
}

type Worker struct {
	store WorkerStore
	cfg   WorkerConfig
}

func NewWorker(store WorkerStore, cfg WorkerConfig) *Worker {
	if cfg.WorkerID == "" {
		cfg.WorkerID = "correlation-worker"
	}
	if cfg.PollInterval <= 0 {
		cfg.PollInterval = time.Second
	}
	if cfg.LeaseDuration <= 0 {
		cfg.LeaseDuration = 30 * time.Second
	}
	if cfg.SnapshotLimit <= 0 {
		cfg.SnapshotLimit = 1000
	}
	if cfg.EngineConfig.HighThreshold <= 0 {
		cfg.EngineConfig = DefaultShadowConfig()
	}
	if cfg.Logger == nil {
		cfg.Logger = slog.Default()
	}
	return &Worker{store: store, cfg: cfg}
}

func (w *Worker) Run(ctx context.Context) {
	ticker := time.NewTicker(w.cfg.PollInterval)
	defer ticker.Stop()
	for {
		worked, err := w.RunOnce(ctx)
		if err != nil && !errors.Is(err, context.Canceled) {
			w.cfg.Logger.Warn("incident correlation worker iteration failed", "error_class", workerErrorClass(err))
		}
		if worked {
			continue
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func (w *Worker) RunOnce(ctx context.Context) (bool, error) {
	job, err := w.store.ClaimCorrelationJob(ctx, w.cfg.WorkerID, w.cfg.LeaseDuration)
	if errors.Is(err, storage.ErrNotFound) {
		return false, nil
	}
	if err != nil {
		return false, err
	}

	if err := w.processJob(ctx, *job); err != nil {
		class := workerErrorClass(err)
		backoff := correlationRetryBackoff(job.AttemptCount)
		state, markErr := w.store.RetryOrFailCorrelationJob(ctx, *job, w.cfg.WorkerID, class, time.Now().UTC().Add(backoff))
		if markErr != nil {
			return true, fmt.Errorf("process: %w; retry-state: %v", err, markErr)
		}
		w.cfg.Logger.Warn("incident correlation job did not complete",
			"job_ref", shortRef("job", job.JobID), "report_ref", shortRef("report", job.ReportID),
			"attempt", job.AttemptCount, "state", state, "error_class", class)
		return true, nil
	}
	if err := w.store.CompleteCorrelationJob(ctx, job.JobID, w.cfg.WorkerID); err != nil {
		return true, err
	}
	w.cfg.Logger.Info("incident correlation shadow job completed",
		"job_ref", shortRef("job", job.JobID), "report_ref", shortRef("report", job.ReportID),
		"attempt", job.AttemptCount, "engine_version", EngineVersion)
	return true, nil
}

func (w *Worker) processJob(ctx context.Context, job storage.CorrelationJob) error {
	current, err := w.store.GetCorrelationReportSnapshot(ctx, job.ReportID)
	if err != nil {
		return fmt.Errorf("load_current_report: %w", err)
	}
	if current.Evidence.Revision < job.TriggerEvidenceRevision {
		return errors.New("evidence_revision_not_visible")
	}
	initialEvidence := reportEvidenceFromSnapshot(*current)
	scopeKeys := correlationScopeKeys(initialEvidence)
	release, err := w.store.AcquireCorrelationScopeLocks(ctx, scopeKeys)
	if err != nil {
		return fmt.Errorf("acquire_scope_lock: %w", err)
	}
	defer release()

	// Re-read after acquiring the scope lock. If evidence changed the electrical/admin
	// scope while this job was waiting, retry from the latest projection.
	current, err = w.store.GetCorrelationReportSnapshot(ctx, job.ReportID)
	if err != nil {
		return fmt.Errorf("reload_current_report: %w", err)
	}
	currentEvidence := reportEvidenceFromSnapshot(*current)
	if !stringSlicesEqual(correlationScopeKeys(currentEvidence), scopeKeys) {
		return errors.New("correlation_scope_changed_retry")
	}

	snapshots, err := w.store.ListCorrelationReportSnapshots(ctx, w.cfg.SnapshotLimit)
	if err != nil {
		return fmt.Errorf("list_candidate_reports: %w", err)
	}
	snapshots = ensureSnapshot(snapshots, *current)
	reports := make([]ReportEvidence, 0, len(snapshots))
	for _, snapshot := range snapshots {
		reports = append(reports, reportEvidenceFromSnapshot(snapshot))
	}
	reports = candidateScopeReports(currentEvidence, reports)
	for _, other := range reports {
		if other.ReportID == currentEvidence.ReportID {
			continue
		}
		result := ScoreRelationship(currentEvidence, other, w.cfg.EngineConfig)
		state := "WEAK_OR_UNRELATED"
		switch {
		case !result.EligibleForUnplanned:
			state = "PLANNED_OUTAGE_SEPARATE_LANE"
		case result.HardVeto:
			state = "CONFLICT"
		case result.ConfidenceLevel == ConfidenceHigh || result.ConfidenceLevel == ConfidenceMedium:
			state = "SUSPECTED"
		}
		if _, _, err := w.store.InsertCorrelationRelationship(ctx, storage.CorrelationRelationship{
			ReportAID:         result.ReportAID,
			ReportBID:         result.ReportBID,
			DecisionHash:      result.DecisionHash,
			ConfidenceScore:   result.ConfidenceScore,
			ConfidenceLevel:   result.ConfidenceLevel,
			HardVeto:          result.HardVeto,
			RelationshipState: state,
			EvidenceJSON:      mustJSON(result),
			EngineVersion:     EngineVersion,
			CreatedAt:         time.Now().UTC(),
		}); err != nil {
			return fmt.Errorf("persist_relationship: %w", err)
		}
	}

	candidates := BuildConservativeClusters(reports, w.cfg.EngineConfig)
	return w.persistClusterProjection(ctx, job, reports, candidates)
}

func (w *Worker) persistClusterProjection(ctx context.Context, job storage.CorrelationJob, reports []ReportEvidence, candidates []ClusterCandidate) error {
	latest, err := w.store.ListLatestCorrelationMemberships(ctx)
	if err != nil {
		return fmt.Errorf("list_latest_memberships: %w", err)
	}
	previous := map[string]storage.CorrelationMembershipRevision{}
	oldMembers := map[string]map[string]struct{}{}
	for _, membership := range latest {
		if membership.MembershipState != "ACTIVE" {
			continue
		}
		previous[membership.ReportID] = membership
		if oldMembers[membership.ClusterID] == nil {
			oldMembers[membership.ClusterID] = map[string]struct{}{}
		}
		oldMembers[membership.ClusterID][membership.ReportID] = struct{}{}
	}

	eligibleGroups := make([]ClusterCandidate, 0)
	groupForReport := map[string]int{}
	for _, candidate := range candidates {
		if len(candidate.ReportIDs) < 2 || candidate.ConfidenceScore < w.cfg.EngineConfig.ClusterJoinThreshold {
			continue
		}
		idx := len(eligibleGroups)
		eligibleGroups = append(eligibleGroups, candidate)
		for _, reportID := range candidate.ReportIDs {
			groupForReport[reportID] = idx
		}
	}

	splitOld := map[string]bool{}
	for clusterID, members := range oldMembers {
		targets := map[int]struct{}{}
		missing := false
		for reportID := range members {
			idx, ok := groupForReport[reportID]
			if !ok {
				missing = true
				continue
			}
			targets[idx] = struct{}{}
		}
		if missing || len(targets) > 1 {
			splitOld[clusterID] = true
		}
	}

	resolvedClusterIDs := make([]string, len(eligibleGroups))
	for i, candidate := range eligibleGroups {
		oldIDs := distinctOldClusters(candidate.ReportIDs, previous)
		switch {
		case len(oldIDs) == 1 && !splitOld[oldIDs[0]]:
			resolvedClusterIDs[i] = oldIDs[0]
		case len(oldIDs) > 1:
			resolvedClusterIDs[i] = projectedClusterID("merge", candidate.ReportIDs, job.JobID)
		default:
			kind := "new"
			if len(oldIDs) == 1 && splitOld[oldIDs[0]] {
				kind = "split"
			}
			resolvedClusterIDs[i] = projectedClusterID(kind, candidate.ReportIDs, job.JobID)
		}
	}

	newAssignment := map[string]string{}
	candidateByCluster := map[string]ClusterCandidate{}
	for i, candidate := range eligibleGroups {
		clusterID := resolvedClusterIDs[i]
		candidate.ClusterID = clusterID
		candidateByCluster[clusterID] = candidate
		for _, reportID := range candidate.ReportIDs {
			newAssignment[reportID] = clusterID
		}
		if _, err := w.store.InsertCorrelationCluster(ctx, storage.CorrelationCluster{
			ClusterID: clusterID, CreatedAt: time.Now().UTC(), CreatedEngineVersion: EngineVersion, Mode: "shadow",
		}); err != nil {
			return fmt.Errorf("insert_cluster: %w", err)
		}
		hypothesis := topologyHypothesis(candidate.ReportIDs, reports)
		summary := map[string]any{
			"report_ids":                     candidate.ReportIDs,
			"confidence_score":               candidate.ConfidenceScore,
			"confidence_level":               candidate.ConfidenceLevel,
			"precision_first":                true,
			"operational_incident_confirmed": false,
			"root_cause_confirmed":           false,
		}
		decisionHash := stableHash(map[string]any{
			"cluster_id": clusterID, "reports": candidate.ReportIDs,
			"score": candidate.ConfidenceScore, "level": candidate.ConfidenceLevel,
			"topology": hypothesis, "engine": EngineVersion,
		})
		expectedRevision := 0
		latestRevision, latestErr := w.store.GetLatestCorrelationClusterRevision(ctx, clusterID)
		if latestErr == nil {
			expectedRevision = latestRevision.Revision
		} else if !errors.Is(latestErr, storage.ErrNotFound) {
			return fmt.Errorf("load_expected_cluster_revision: %w", latestErr)
		}
		if _, _, err := w.store.InsertCorrelationClusterRevision(ctx, storage.CorrelationClusterRevision{
			ClusterID: clusterID, ExpectedRevision: &expectedRevision, DecisionHash: decisionHash, LifecycleState: "ACTIVE",
			CorrelationStatus: "SUSPECTED_RELATED", ConfidenceScore: candidate.ConfidenceScore,
			ConfidenceLevel: candidate.ConfidenceLevel, RawReportCount: candidate.RawReportCount,
			UniqueReporterCount: candidate.UniqueReporterCount, TopologyHypothesisJSON: mustJSON(hypothesis),
			EvidenceSummaryJSON: mustJSON(summary), EngineVersion: EngineVersion, CreatedAt: time.Now().UTC(),
		}); err != nil {
			return fmt.Errorf("insert_cluster_revision: %w", err)
		}
	}

	// Persist lineage after all child clusters exist.
	for i, candidate := range eligibleGroups {
		newID := resolvedClusterIDs[i]
		oldIDs := distinctOldClusters(candidate.ReportIDs, previous)
		if len(oldIDs) > 1 {
			for _, oldID := range oldIDs {
				if oldID == newID {
					continue
				}
				if _, err := w.store.InsertCorrelationClusterLineage(ctx, storage.CorrelationClusterLineage{
					ParentClusterID: oldID, ChildClusterID: newID, RelationType: "MERGE",
					Reason:        "deterministic_shadow_projection_merged_previous_clusters",
					EngineVersion: EngineVersion, CreatedAt: time.Now().UTC(),
				}); err != nil {
					return fmt.Errorf("insert_merge_lineage: %w", err)
				}
				if err := w.markClusterLifecycle(ctx, oldID, "SUPERSEDED_BY_MERGE", "merged_into_"+newID); err != nil {
					return err
				}
			}
		} else if len(oldIDs) == 1 && splitOld[oldIDs[0]] && oldIDs[0] != newID {
			oldID := oldIDs[0]
			if _, err := w.store.InsertCorrelationClusterLineage(ctx, storage.CorrelationClusterLineage{
				ParentClusterID: oldID, ChildClusterID: newID, RelationType: "SPLIT",
				Reason:        "deterministic_shadow_projection_split_previous_cluster",
				EngineVersion: EngineVersion, CreatedAt: time.Now().UTC(),
			}); err != nil {
				return fmt.Errorf("insert_split_lineage: %w", err)
			}
			if err := w.markClusterLifecycle(ctx, oldID, "SPLIT", "split_into_child_clusters"); err != nil {
				return err
			}
		}
	}

	reportSet := map[string]struct{}{}
	for _, report := range reports {
		reportSet[report.ReportID] = struct{}{}
	}
	for reportID := range reportSet {
		prev, hasPrev := previous[reportID]
		newID := newAssignment[reportID]
		if hasPrev && prev.ClusterID != newID {
			if _, _, err := w.store.InsertCorrelationMembershipRevision(ctx, storage.CorrelationMembershipRevision{
				ReportID: reportID, ClusterID: prev.ClusterID, MembershipState: "REMOVED",
				AssignmentReason: "shadow_recompute_changed_membership", ConfidenceScore: prev.ConfidenceScore,
				ConfidenceLevel: prev.ConfidenceLevel, EngineVersion: EngineVersion,
				DecisionHash: stableHash(map[string]any{"report": reportID, "cluster": prev.ClusterID, "state": "REMOVED", "job": job.JobID, "engine": EngineVersion}),
				CreatedAt:    time.Now().UTC(),
			}); err != nil {
				return fmt.Errorf("remove_membership: %w", err)
			}
		}
		if newID == "" {
			continue
		}
		candidate := candidateByCluster[newID]
		if _, _, err := w.store.InsertCorrelationMembershipRevision(ctx, storage.CorrelationMembershipRevision{
			ReportID: reportID, ClusterID: newID, MembershipState: "ACTIVE",
			AssignmentReason: "deterministic_complete_link_shadow_projection",
			ConfidenceScore:  candidate.ConfidenceScore, ConfidenceLevel: candidate.ConfidenceLevel,
			EngineVersion: EngineVersion,
			DecisionHash:  stableHash(map[string]any{"report": reportID, "cluster": newID, "state": "ACTIVE", "score": candidate.ConfidenceScore, "level": candidate.ConfidenceLevel, "engine": EngineVersion}),
			CreatedAt:     time.Now().UTC(),
		}); err != nil {
			return fmt.Errorf("activate_membership: %w", err)
		}
	}

	// If an old cluster lost members and no child group retained them, preserve the historical
	// cluster but close its active projection as SPLIT rather than deleting it.
	for oldID := range splitOld {
		if _, stillActive := candidateByCluster[oldID]; stillActive {
			continue
		}
		if err := w.markClusterLifecycle(ctx, oldID, "SPLIT", "shadow_recompute_removed_or_split_members"); err != nil && !errors.Is(err, storage.ErrNotFound) {
			return err
		}
	}
	return nil
}

func (w *Worker) markClusterLifecycle(ctx context.Context, clusterID, lifecycle, reason string) error {
	latest, err := w.store.GetLatestCorrelationClusterRevision(ctx, clusterID)
	if err != nil {
		return fmt.Errorf("load_cluster_revision: %w", err)
	}
	if latest.LifecycleState == lifecycle {
		return nil
	}
	decisionHash := stableHash(map[string]any{
		"cluster_id": clusterID, "lifecycle": lifecycle, "reason": reason, "engine": EngineVersion,
	})
	expectedRevision := latest.Revision
	_, _, err = w.store.InsertCorrelationClusterRevision(ctx, storage.CorrelationClusterRevision{
		ClusterID: clusterID, ExpectedRevision: &expectedRevision, DecisionHash: decisionHash, LifecycleState: lifecycle,
		CorrelationStatus: latest.CorrelationStatus, ConfidenceScore: latest.ConfidenceScore,
		ConfidenceLevel: latest.ConfidenceLevel, RawReportCount: latest.RawReportCount,
		UniqueReporterCount: latest.UniqueReporterCount, TopologyHypothesisJSON: latest.TopologyHypothesisJSON,
		EvidenceSummaryJSON: latest.EvidenceSummaryJSON, EngineVersion: EngineVersion, CreatedAt: time.Now().UTC(),
	})
	if err != nil {
		return fmt.Errorf("mark_cluster_lifecycle: %w", err)
	}
	return nil
}

func reportEvidenceFromSnapshot(snapshot storage.CorrelationReportSnapshot) ReportEvidence {
	location := struct {
		Province    string `json:"province"`
		District    string `json:"district"`
		Subdistrict string `json:"subdistrict"`
		Village     string `json:"village"`
	}{}
	_ = json.Unmarshal(snapshot.Evidence.LocationJSON, &location)
	topology := struct {
		FeederID              string   `json:"feeder_id"`
		TransformerIDs        []string `json:"transformer_ids"`
		UpstreamProtectionIDs []string `json:"upstream_protection_ids"`
		Authoritative         bool     `json:"authoritative"`
	}{}
	_ = json.Unmarshal(snapshot.Evidence.TopologyJSON, &topology)
	freshness := struct {
		Topology string `json:"topology"`
	}{}
	_ = json.Unmarshal(snapshot.Evidence.FreshnessJSON, &freshness)
	reporterRef := ""
	if snapshot.Report.SessionRefHash != "" {
		// Channel is deliberately included: this deduplicates a stable pseudonymous
		// identity inside one channel, but never guesses cross-channel identity.
		reporterRef = snapshot.Report.SourceSystem + "|" + snapshot.Report.SourceChannel + "|" + snapshot.Report.SessionRefHash
	}
	return ReportEvidence{
		ReportID: snapshot.Report.ReportID, OccurredAt: snapshot.Report.OccurredAt,
		Province: location.Province, District: location.District, Subdistrict: location.Subdistrict, Village: location.Village,
		FeederID: topology.FeederID, TransformerIDs: topology.TransformerIDs,
		UpstreamProtectionIDs: topology.UpstreamProtectionIDs, TopologyFreshness: freshness.Topology,
		TopologyAuthoritative: topology.Authoritative, PlannedOutageState: snapshot.Evidence.PlannedOutageState,
		AuthoritativeReporterRef: reporterRef,
	}
}

func topologyHypothesis(reportIDs []string, reports []ReportEvidence) map[string]any {
	byID := map[string]ReportEvidence{}
	for _, report := range reports {
		byID[report.ReportID] = report
	}
	feeders := map[string]int{}
	transformers := map[string]int{}
	upstream := map[string]int{}
	for _, id := range reportIDs {
		report := byID[id]
		if report.FeederID != "" {
			feeders[report.FeederID]++
		}
		for _, value := range report.TransformerIDs {
			transformers[value]++
		}
		for _, value := range report.UpstreamProtectionIDs {
			upstream[value]++
		}
	}
	return map[string]any{
		"feeder_candidates":              rankedCounts(feeders),
		"transformer_candidates":         rankedCounts(transformers),
		"upstream_protection_candidates": rankedCounts(upstream),
		"confirmed":                      false,
	}
}

func rankedCounts(values map[string]int) []map[string]any {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Slice(keys, func(i, j int) bool {
		if values[keys[i]] == values[keys[j]] {
			return keys[i] < keys[j]
		}
		return values[keys[i]] > values[keys[j]]
	})
	out := make([]map[string]any, 0, len(keys))
	for _, key := range keys {
		out = append(out, map[string]any{"id": key, "support_count": values[key]})
	}
	return out
}

func distinctOldClusters(reportIDs []string, previous map[string]storage.CorrelationMembershipRevision) []string {
	set := map[string]struct{}{}
	for _, reportID := range reportIDs {
		if item, ok := previous[reportID]; ok && item.MembershipState == "ACTIVE" && item.ClusterID != "" {
			set[item.ClusterID] = struct{}{}
		}
	}
	out := make([]string, 0, len(set))
	for value := range set {
		out = append(out, value)
	}
	sort.Strings(out)
	return out
}

func ensureSnapshot(items []storage.CorrelationReportSnapshot, current storage.CorrelationReportSnapshot) []storage.CorrelationReportSnapshot {
	for _, item := range items {
		if item.Report.ReportID == current.Report.ReportID {
			return items
		}
	}
	return append(items, current)
}

func projectedClusterID(kind string, reportIDs []string, jobID string) string {
	ids := append([]string(nil), reportIDs...)
	sort.Strings(ids)
	return "clu_" + stableHash(map[string]any{"kind": kind, "reports": ids, "job": jobID})[:16]
}

func stableHash(value any) string {
	raw, _ := json.Marshal(value)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func mustJSON(value any) json.RawMessage {
	raw, err := json.Marshal(value)
	if err != nil {
		return json.RawMessage(`{}`)
	}
	return raw
}

func shortRef(namespace, value string) string {
	if strings.TrimSpace(value) == "" {
		return ""
	}
	sum := sha256.Sum256([]byte(namespace + "|" + value))
	return namespace + "_" + hex.EncodeToString(sum[:])[:12]
}

func workerErrorClass(err error) string {
	if err == nil {
		return ""
	}
	text := strings.ToLower(err.Error())
	switch {
	case errors.Is(err, context.DeadlineExceeded) || strings.Contains(text, "timeout"):
		return "TIMEOUT"
	case errors.Is(err, storage.ErrCorrelationRevisionConflict) || strings.Contains(text, "correlation_scope_changed_retry"):
		return "REVISION_CONFLICT"
	case strings.Contains(text, "lost lease"):
		return "LEASE_CONFLICT"
	case strings.Contains(text, "evidence_revision"):
		return "EVIDENCE_NOT_READY"
	case strings.Contains(text, "not found"):
		return "DEPENDENCY_NOT_FOUND"
	default:
		return "PROCESSING_ERROR"
	}
}

func correlationRetryBackoff(attempt int) time.Duration {
	if attempt < 1 {
		attempt = 1
	}
	if attempt > 6 {
		attempt = 6
	}
	return time.Duration(1<<(attempt-1)) * time.Second
}

func correlationScopeKeys(report ReportEvidence) []string {
	report = normalizeEvidence(report)
	set := map[string]struct{}{}
	if report.FeederID != "" {
		set["feeder:"+report.FeederID] = struct{}{}
	}
	for _, value := range report.UpstreamProtectionIDs {
		set["upstream:"+value] = struct{}{}
	}
	for _, value := range report.TransformerIDs {
		set["transformer:"+value] = struct{}{}
	}
	adminParts := []string{report.Province, report.District, report.Subdistrict}
	if strings.Trim(strings.Join(adminParts, ""), " ") != "" {
		set["admin:"+strings.Join(adminParts, "|")] = struct{}{}
	}
	if len(set) == 0 {
		set["report:"+report.ReportID] = struct{}{}
	}
	out := make([]string, 0, len(set))
	for value := range set {
		out = append(out, value)
	}
	sort.Strings(out)
	return out
}

func stringSlicesEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func candidateScopeReports(current ReportEvidence, reports []ReportEvidence) []ReportEvidence {
	current = normalizeEvidence(current)
	out := make([]ReportEvidence, 0, len(reports))
	for _, candidate := range reports {
		candidate = normalizeEvidence(candidate)
		if candidate.ReportID == current.ReportID {
			out = append(out, candidate)
			continue
		}
		if sharedValue(current.TransformerIDs, candidate.TransformerIDs) ||
			sharedValue(current.UpstreamProtectionIDs, candidate.UpstreamProtectionIDs) ||
			nonEmptyEqual(current.FeederID, candidate.FeederID) {
			out = append(out, candidate)
			continue
		}
		if hasTopologyEvidence(current) && hasTopologyEvidence(candidate) {
			continue
		}
		if adminFallbackCompatible(current, candidate) {
			out = append(out, candidate)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].OccurredAt.Equal(out[j].OccurredAt) {
			return out[i].ReportID < out[j].ReportID
		}
		return out[i].OccurredAt.Before(out[j].OccurredAt)
	})
	return out
}

func hasTopologyEvidence(report ReportEvidence) bool {
	return report.FeederID != "" || len(report.TransformerIDs) > 0 || len(report.UpstreamProtectionIDs) > 0
}

func adminFallbackCompatible(a, b ReportEvidence) bool {
	if a.Province != "" && b.Province != "" && !nonEmptyEqual(a.Province, b.Province) {
		return false
	}
	if a.Subdistrict != "" && b.Subdistrict != "" {
		return nonEmptyEqual(a.Subdistrict, b.Subdistrict)
	}
	if a.District != "" && b.District != "" {
		return nonEmptyEqual(a.District, b.District)
	}
	if a.Province != "" && b.Province != "" {
		return nonEmptyEqual(a.Province, b.Province)
	}
	return false
}
