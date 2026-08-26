package correlation

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math"
	"sort"
	"strings"
	"time"
)

const EngineVersion = "incident-correlation-shadow-v1.0.0"

const (
	ConfidenceLow    = "LOW"
	ConfidenceMedium = "MEDIUM"
	ConfidenceHigh   = "HIGH"
)

const (
	FreshnessFresh       = "FRESH"
	FreshnessStale       = "STALE"
	FreshnessUnknown     = "UNKNOWN"
	FreshnessUnavailable = "UNAVAILABLE"
)

const (
	PlannedNotChecked   = "NOT_CHECKED"
	PlannedNoMatch      = "NO_MATCH"
	PlannedMatched      = "MATCHED"
	PlannedAmbiguous    = "AMBIGUOUS"
	PlannedUnavailable  = "UNAVAILABLE"
	PlannedInconclusive = "INCONCLUSIVE"
)

type Config struct {
	SameTransformerWeight float64
	SameFeederWeight      float64
	SharedUpstreamWeight  float64
	SameVillageWeight     float64
	SameSubdistrictWeight float64
	SameDistrictWeight    float64
	SameProvinceWeight    float64
	TimeMaxWeight         float64
	TimeDecayHours        float64
	MediumThreshold       float64
	HighThreshold         float64
	ClusterJoinThreshold  float64
}

func DefaultShadowConfig() Config {
	return Config{
		SameTransformerWeight: 45,
		SameFeederWeight:      22,
		SharedUpstreamWeight:  16,
		SameVillageWeight:     8,
		SameSubdistrictWeight: 5,
		SameDistrictWeight:    3,
		SameProvinceWeight:    1,
		TimeMaxWeight:         12,
		TimeDecayHours:        2,
		MediumThreshold:       45,
		HighThreshold:         75,
		ClusterJoinThreshold:  45,
	}
}

type ReportEvidence struct {
	ReportID                 string
	OccurredAt               time.Time
	Province                 string
	District                 string
	Subdistrict              string
	Village                  string
	FeederID                 string
	TransformerIDs           []string
	UpstreamProtectionIDs    []string
	TopologyFreshness        string
	TopologyAuthoritative    bool
	PlannedOutageState       string
	AuthoritativeReporterRef string
}

type Contribution struct {
	Feature string  `json:"feature"`
	Kind    string  `json:"kind"`
	Score   float64 `json:"score"`
	Detail  string  `json:"detail,omitempty"`
}

type RelationshipResult struct {
	ReportAID            string         `json:"report_a_id"`
	ReportBID            string         `json:"report_b_id"`
	ConfidenceScore      float64        `json:"confidence_score"`
	ConfidenceLevel      string         `json:"confidence_level"`
	ConfidenceCeiling    string         `json:"confidence_ceiling,omitempty"`
	HardVeto             bool           `json:"hard_veto"`
	EligibleForUnplanned bool           `json:"eligible_for_unplanned"`
	Flags                []string       `json:"flags,omitempty"`
	Contributions        []Contribution `json:"contributions"`
	EngineVersion        string         `json:"engine_version"`
	DecisionHash         string         `json:"decision_hash"`
}

type ClusterCandidate struct {
	ClusterID           string   `json:"cluster_id"`
	ReportIDs           []string `json:"report_ids"`
	ConfidenceScore     float64  `json:"confidence_score"`
	ConfidenceLevel     string   `json:"confidence_level"`
	RawReportCount      int      `json:"raw_report_count"`
	UniqueReporterCount int      `json:"unique_reporter_count"`
	EngineVersion       string   `json:"engine_version"`
}

func ScoreRelationship(a, b ReportEvidence, cfg Config) RelationshipResult {
	a, b = canonicalPair(a, b)
	result := RelationshipResult{
		ReportAID:            a.ReportID,
		ReportBID:            b.ReportID,
		EligibleForUnplanned: true,
		EngineVersion:        EngineVersion,
	}

	if a.PlannedOutageState == PlannedMatched || b.PlannedOutageState == PlannedMatched {
		result.EligibleForUnplanned = false
		result.Flags = append(result.Flags, "PLANNED_OUTAGE_SEPARATE_LANE")
		result.ConfidenceScore = 0
		result.ConfidenceLevel = ConfidenceLow
		result.DecisionHash = relationshipHash(result)
		return result
	}

	freshAuthoritative := topologyFreshAuthoritative(a) && topologyFreshAuthoritative(b)
	sharedTX := sharedValue(a.TransformerIDs, b.TransformerIDs)
	sharedUpstream := sharedValue(a.UpstreamProtectionIDs, b.UpstreamProtectionIDs)
	sameFeeder := nonEmptyEqual(a.FeederID, b.FeederID)

	if freshAuthoritative && a.FeederID != "" && b.FeederID != "" && !sameFeeder && !sharedTX && !sharedUpstream {
		result.HardVeto = true
		result.Contributions = append(result.Contributions, Contribution{
			Feature: "authoritative_topology_conflict",
			Kind:    "NEGATIVE_HARD_VETO",
			Score:   -100,
			Detail:  "different known feeders without shared transformer/upstream protection",
		})
		result.ConfidenceScore = 0
		result.ConfidenceLevel = ConfidenceLow
		result.Flags = append(result.Flags, "STRONG_TOPOLOGY_CONFLICT")
		result.DecisionHash = relationshipHash(result)
		return result
	}

	score := 0.0
	if sharedTX {
		score += cfg.SameTransformerWeight
		result.Contributions = append(result.Contributions, Contribution{Feature: "same_transformer", Kind: "POSITIVE_STRONG", Score: cfg.SameTransformerWeight})
	}
	if sameFeeder {
		score += cfg.SameFeederWeight
		result.Contributions = append(result.Contributions, Contribution{Feature: "same_feeder", Kind: "POSITIVE_MEDIUM", Score: cfg.SameFeederWeight})
	}
	if sharedUpstream {
		score += cfg.SharedUpstreamWeight
		result.Contributions = append(result.Contributions, Contribution{Feature: "shared_upstream_protection", Kind: "POSITIVE_MEDIUM", Score: cfg.SharedUpstreamWeight})
	}

	if nonEmptyEqual(a.Village, b.Village) {
		score += cfg.SameVillageWeight
		result.Contributions = append(result.Contributions, Contribution{Feature: "same_village", Kind: "POSITIVE_SUPPORTING", Score: cfg.SameVillageWeight})
	} else if a.Village != "" && b.Village != "" {
		score -= 3
		result.Contributions = append(result.Contributions, Contribution{Feature: "different_village", Kind: "NEGATIVE_WEAK", Score: -3})
	}
	if nonEmptyEqual(a.Subdistrict, b.Subdistrict) {
		score += cfg.SameSubdistrictWeight
		result.Contributions = append(result.Contributions, Contribution{Feature: "same_subdistrict", Kind: "POSITIVE_SUPPORTING", Score: cfg.SameSubdistrictWeight})
	} else if a.Subdistrict != "" && b.Subdistrict != "" {
		score -= 2
		result.Contributions = append(result.Contributions, Contribution{Feature: "different_subdistrict", Kind: "NEGATIVE_WEAK", Score: -2})
	}
	if nonEmptyEqual(a.District, b.District) {
		score += cfg.SameDistrictWeight
		result.Contributions = append(result.Contributions, Contribution{Feature: "same_district", Kind: "POSITIVE_SUPPORTING", Score: cfg.SameDistrictWeight})
	}
	if nonEmptyEqual(a.Province, b.Province) {
		score += cfg.SameProvinceWeight
		result.Contributions = append(result.Contributions, Contribution{Feature: "same_province", Kind: "POSITIVE_SUPPORTING", Score: cfg.SameProvinceWeight})
	}

	timeScore := softTimeContribution(a.OccurredAt, b.OccurredAt, cfg.TimeMaxWeight, cfg.TimeDecayHours)
	if timeScore > 0 {
		score += timeScore
		result.Contributions = append(result.Contributions, Contribution{Feature: "time_proximity", Kind: "POSITIVE_SUPPORTING", Score: round2(timeScore)})
	}

	ceiling := ""
	if !freshAuthoritative {
		ceiling = ConfidenceMedium
		result.Flags = append(result.Flags, "TOPOLOGY_NOT_FRESH_AUTHORITATIVE")
	}
	if plannedUncertain(a.PlannedOutageState) || plannedUncertain(b.PlannedOutageState) {
		ceiling = ConfidenceMedium
		result.Flags = append(result.Flags, "PLANNED_OUTAGE_UNCERTAIN")
	}

	result.ConfidenceScore = clamp(round2(score), 0, 100)
	result.ConfidenceLevel = scoreLevel(result.ConfidenceScore, cfg)
	if ceiling == ConfidenceMedium && result.ConfidenceLevel == ConfidenceHigh {
		result.ConfidenceLevel = ConfidenceMedium
		result.ConfidenceCeiling = ConfidenceMedium
	}
	result.DecisionHash = relationshipHash(result)
	return result
}

func BuildConservativeClusters(reports []ReportEvidence, cfg Config) []ClusterCandidate {
	items := append([]ReportEvidence(nil), reports...)
	sort.Slice(items, func(i, j int) bool {
		if items[i].OccurredAt.Equal(items[j].OccurredAt) {
			return items[i].ReportID < items[j].ReportID
		}
		return items[i].OccurredAt.Before(items[j].OccurredAt)
	})

	clusters := make([][]ReportEvidence, 0)
	for _, report := range items {
		best := -1
		bestMin := -1.0
		for i, cluster := range clusters {
			minScore, ok := canJoinCluster(report, cluster, cfg)
			if ok && minScore > bestMin {
				best = i
				bestMin = minScore
			}
		}
		if best < 0 {
			clusters = append(clusters, []ReportEvidence{report})
			continue
		}
		clusters[best] = append(clusters[best], report)
	}

	out := make([]ClusterCandidate, 0, len(clusters))
	for _, members := range clusters {
		reportIDs := make([]string, 0, len(members))
		for _, member := range members {
			reportIDs = append(reportIDs, member.ReportID)
		}
		sort.Strings(reportIDs)
		score := 0.0
		level := ConfidenceLow
		if len(members) > 1 {
			score = 100
			for i := 0; i < len(members); i++ {
				for j := i + 1; j < len(members); j++ {
					rel := ScoreRelationship(members[i], members[j], cfg)
					if rel.ConfidenceScore < score {
						score = rel.ConfidenceScore
					}
				}
			}
			level = scoreLevel(score, cfg)
		}
		out = append(out, ClusterCandidate{
			ClusterID:           clusterID(reportIDs),
			ReportIDs:           reportIDs,
			ConfidenceScore:     round2(score),
			ConfidenceLevel:     level,
			RawReportCount:      len(members),
			UniqueReporterCount: uniqueReporterCount(members),
			EngineVersion:       EngineVersion,
		})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ClusterID < out[j].ClusterID })
	return out
}

func canJoinCluster(report ReportEvidence, cluster []ReportEvidence, cfg Config) (float64, bool) {
	if report.PlannedOutageState == PlannedMatched {
		return 0, false
	}
	minScore := 100.0
	for _, member := range cluster {
		rel := ScoreRelationship(report, member, cfg)
		if rel.HardVeto || !rel.EligibleForUnplanned || rel.ConfidenceScore < cfg.ClusterJoinThreshold {
			return 0, false
		}
		if rel.ConfidenceScore < minScore {
			minScore = rel.ConfidenceScore
		}
	}
	return minScore, true
}

func canonicalPair(a, b ReportEvidence) (ReportEvidence, ReportEvidence) {
	if a.ReportID <= b.ReportID {
		return normalizeEvidence(a), normalizeEvidence(b)
	}
	return normalizeEvidence(b), normalizeEvidence(a)
}

func normalizeEvidence(in ReportEvidence) ReportEvidence {
	in.ReportID = strings.TrimSpace(in.ReportID)
	in.Province = normalizeText(in.Province)
	in.District = normalizeText(in.District)
	in.Subdistrict = normalizeText(in.Subdistrict)
	in.Village = normalizeText(in.Village)
	in.FeederID = strings.ToUpper(strings.TrimSpace(in.FeederID))
	in.TransformerIDs = normalizeList(in.TransformerIDs)
	in.UpstreamProtectionIDs = normalizeList(in.UpstreamProtectionIDs)
	in.TopologyFreshness = strings.ToUpper(strings.TrimSpace(in.TopologyFreshness))
	in.PlannedOutageState = strings.ToUpper(strings.TrimSpace(in.PlannedOutageState))
	return in
}

func topologyFreshAuthoritative(in ReportEvidence) bool {
	return in.TopologyAuthoritative && strings.EqualFold(strings.TrimSpace(in.TopologyFreshness), FreshnessFresh)
}

func plannedUncertain(value string) bool {
	switch strings.ToUpper(strings.TrimSpace(value)) {
	case PlannedAmbiguous, PlannedUnavailable, PlannedInconclusive:
		return true
	default:
		return false
	}
}

func sharedValue(a, b []string) bool {
	if len(a) == 0 || len(b) == 0 {
		return false
	}
	set := make(map[string]struct{}, len(a))
	for _, value := range normalizeList(a) {
		set[value] = struct{}{}
	}
	for _, value := range normalizeList(b) {
		if _, ok := set[value]; ok {
			return true
		}
	}
	return false
}

func nonEmptyEqual(a, b string) bool {
	a = strings.TrimSpace(a)
	b = strings.TrimSpace(b)
	return a != "" && b != "" && strings.EqualFold(a, b)
}

func normalizeList(values []string) []string {
	set := map[string]struct{}{}
	for _, value := range values {
		value = strings.ToUpper(strings.TrimSpace(value))
		if value != "" {
			set[value] = struct{}{}
		}
	}
	out := make([]string, 0, len(set))
	for value := range set {
		out = append(out, value)
	}
	sort.Strings(out)
	return out
}

func normalizeText(value string) string {
	return strings.ToLower(strings.Join(strings.Fields(strings.TrimSpace(value)), " "))
}

func softTimeContribution(a, b time.Time, maxWeight, decayHours float64) float64 {
	if a.IsZero() || b.IsZero() || maxWeight <= 0 || decayHours <= 0 {
		return 0
	}
	delta := a.Sub(b)
	if delta < 0 {
		delta = -delta
	}
	return maxWeight * math.Exp(-delta.Hours()/decayHours)
}

func scoreLevel(score float64, cfg Config) string {
	switch {
	case score >= cfg.HighThreshold:
		return ConfidenceHigh
	case score >= cfg.MediumThreshold:
		return ConfidenceMedium
	default:
		return ConfidenceLow
	}
}

func relationshipHash(result RelationshipResult) string {
	copyResult := result
	copyResult.DecisionHash = ""
	copyResult.Flags = append([]string(nil), result.Flags...)
	sort.Strings(copyResult.Flags)
	copyResult.Contributions = append([]Contribution(nil), result.Contributions...)
	sort.Slice(copyResult.Contributions, func(i, j int) bool {
		if copyResult.Contributions[i].Feature == copyResult.Contributions[j].Feature {
			return copyResult.Contributions[i].Kind < copyResult.Contributions[j].Kind
		}
		return copyResult.Contributions[i].Feature < copyResult.Contributions[j].Feature
	})
	raw, _ := json.Marshal(copyResult)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func clusterID(reportIDs []string) string {
	ids := append([]string(nil), reportIDs...)
	sort.Strings(ids)
	raw, _ := json.Marshal(ids)
	sum := sha256.Sum256(raw)
	return "clu_" + hex.EncodeToString(sum[:8])
}

func uniqueReporterCount(reports []ReportEvidence) int {
	seen := map[string]struct{}{}
	for _, report := range reports {
		key := strings.TrimSpace(report.AuthoritativeReporterRef)
		if key == "" {
			key = "unknown:" + report.ReportID
		}
		seen[key] = struct{}{}
	}
	return len(seen)
}

func clamp(value, min, max float64) float64 {
	if value < min {
		return min
	}
	if value > max {
		return max
	}
	return value
}

func round2(value float64) float64 {
	return math.Round(value*100) / 100
}
