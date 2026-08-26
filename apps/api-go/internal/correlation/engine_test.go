package correlation

import (
	"testing"
	"time"
)

func baseReport(id string, at time.Time) ReportEvidence {
	return ReportEvidence{
		ReportID:              id,
		OccurredAt:            at,
		Province:              "บึงกาฬ",
		District:              "เมืองบึงกาฬ",
		Subdistrict:           "บึงกาฬ",
		Village:               "บ้านดงหมากยาง",
		FeederID:              "BUA03",
		TransformerIDs:        []string{"63-006344"},
		UpstreamProtectionIDs: []string{"REC-BUA03-01"},
		TopologyFreshness:     FreshnessFresh,
		TopologyAuthoritative: true,
		PlannedOutageState:    PlannedNoMatch,
	}
}

func TestSameTransformerFreshAuthoritativeCanReachHigh(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	b := baseReport("r-b", now.Add(4*time.Minute))
	result := ScoreRelationship(a, b, cfg)
	if result.HardVeto {
		t.Fatalf("same transformer must not hard veto: %#v", result)
	}
	if result.ConfidenceLevel != ConfidenceHigh {
		t.Fatalf("expected HIGH relationship for strong fresh topology, got %#v", result)
	}
	if result.ConfidenceScore < cfg.HighThreshold {
		t.Fatalf("expected score above HIGH threshold, got %.2f", result.ConfidenceScore)
	}
}

func TestSameFeederWithoutSameTransformerStaysMedium(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	b := baseReport("r-b", now.Add(5*time.Minute))
	a.TransformerIDs = []string{"TX-A"}
	b.TransformerIDs = []string{"TX-B"}
	a.UpstreamProtectionIDs = nil
	b.UpstreamProtectionIDs = nil
	result := ScoreRelationship(a, b, cfg)
	if result.ConfidenceLevel != ConfidenceMedium {
		t.Fatalf("same feeder with supporting location/time should be MEDIUM under provisional weights, got %#v", result)
	}
}

func TestFreshAuthoritativeDifferentFeedersHardVeto(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	b := baseReport("r-b", now.Add(time.Minute))
	a.FeederID = "BUA03"
	b.FeederID = "BUA04"
	a.TransformerIDs = []string{"TX-A"}
	b.TransformerIDs = []string{"TX-B"}
	a.UpstreamProtectionIDs = []string{"REC-A"}
	b.UpstreamProtectionIDs = []string{"REC-B"}
	result := ScoreRelationship(a, b, cfg)
	if !result.HardVeto || result.ConfidenceScore != 0 {
		t.Fatalf("strong authoritative topology conflict must hard veto, got %#v", result)
	}
}

func TestStaleDifferentFeedersCannotHardVetoAndCapsConfidence(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	b := baseReport("r-b", now.Add(time.Minute))
	a.FeederID = "BUA03"
	b.FeederID = "BUA04"
	a.TopologyFreshness = FreshnessStale
	b.TopologyFreshness = FreshnessStale
	result := ScoreRelationship(a, b, cfg)
	if result.HardVeto {
		t.Fatalf("stale topology alone must not hard veto: %#v", result)
	}
	if result.ConfidenceLevel == ConfidenceHigh {
		t.Fatalf("stale topology must prevent HIGH: %#v", result)
	}
}

func TestPlannedOutageUncertainCapsHigh(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	b := baseReport("r-b", now.Add(time.Minute))
	b.PlannedOutageState = PlannedUnavailable
	result := ScoreRelationship(a, b, cfg)
	if result.ConfidenceLevel == ConfidenceHigh {
		t.Fatalf("planned outage uncertainty must prevent HIGH: %#v", result)
	}
	if result.ConfidenceCeiling != ConfidenceMedium {
		t.Fatalf("expected MEDIUM ceiling for planned outage uncertainty: %#v", result)
	}
}

func TestPlannedOutageMatchedUsesSeparateLane(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	b := baseReport("r-b", now.Add(time.Minute))
	b.PlannedOutageState = PlannedMatched
	result := ScoreRelationship(a, b, cfg)
	if result.EligibleForUnplanned {
		t.Fatalf("planned outage MATCHED must not contribute to suspected unplanned clustering: %#v", result)
	}
}

func TestTimeIsSoftEvidenceNotEligibilityCutoff(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	bShort := baseReport("r-b", now.Add(10*time.Minute))
	bLong := baseReport("r-c", now.Add(10*time.Hour))
	a.TransformerIDs = []string{"TX-A"}
	bShort.TransformerIDs = []string{"TX-B"}
	bLong.TransformerIDs = []string{"TX-C"}
	a.UpstreamProtectionIDs = nil
	bShort.UpstreamProtectionIDs = nil
	bLong.UpstreamProtectionIDs = nil
	shortResult := ScoreRelationship(a, bShort, cfg)
	longResult := ScoreRelationship(a, bLong, cfg)
	if longResult.HardVeto || !longResult.EligibleForUnplanned {
		t.Fatalf("long time separation alone must not make report ineligible: %#v", longResult)
	}
	if shortResult.ConfidenceScore <= longResult.ConfidenceScore {
		t.Fatalf("time contribution should decay smoothly; short %.2f long %.2f", shortResult.ConfidenceScore, longResult.ConfidenceScore)
	}
}

func TestRelationshipHashIsOrderIndependent(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	b := baseReport("r-b", now.Add(time.Minute))
	ab := ScoreRelationship(a, b, cfg)
	ba := ScoreRelationship(b, a, cfg)
	if ab.DecisionHash != ba.DecisionHash || ab.ReportAID != ba.ReportAID || ab.ReportBID != ba.ReportBID {
		t.Fatalf("pair scoring must be canonical/order independent: ab=%#v ba=%#v", ab, ba)
	}
}

func TestConservativeClustersGroupStrongReportsAndSplitConflict(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	b := baseReport("r-b", now.Add(2*time.Minute))
	c := baseReport("r-c", now.Add(3*time.Minute))
	c.FeederID = "BUA04"
	c.TransformerIDs = []string{"TX-C"}
	c.UpstreamProtectionIDs = []string{"REC-C"}
	clusters := BuildConservativeClusters([]ReportEvidence{c, b, a}, cfg)
	if len(clusters) != 2 {
		t.Fatalf("expected two conservative clusters, got %#v", clusters)
	}
	var pair, single *ClusterCandidate
	for i := range clusters {
		if clusters[i].RawReportCount == 2 {
			pair = &clusters[i]
		}
		if clusters[i].RawReportCount == 1 {
			single = &clusters[i]
		}
	}
	if pair == nil || single == nil {
		t.Fatalf("expected one pair and one singleton: %#v", clusters)
	}
	if pair.ConfidenceLevel != ConfidenceHigh {
		t.Fatalf("strong pair should be HIGH in shadow candidate: %#v", pair)
	}
}

func TestUniqueReporterCountDeduplicatesOnlyAuthoritativeReference(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-a", now)
	b := baseReport("r-b", now.Add(time.Minute))
	a.AuthoritativeReporterRef = "anon-link-1"
	b.AuthoritativeReporterRef = "anon-link-1"
	clusters := BuildConservativeClusters([]ReportEvidence{a, b}, cfg)
	if len(clusters) != 1 || clusters[0].UniqueReporterCount != 1 || clusters[0].RawReportCount != 2 {
		t.Fatalf("authoritative reporter link should deduplicate unique count only: %#v", clusters)
	}

	a.AuthoritativeReporterRef = ""
	b.AuthoritativeReporterRef = ""
	clusters = BuildConservativeClusters([]ReportEvidence{a, b}, cfg)
	if len(clusters) != 1 || clusters[0].UniqueReporterCount != 2 {
		t.Fatalf("unknown relationship must not be guessed/deduplicated: %#v", clusters)
	}
}

func TestConservativeClustersAllowMediumSameFeederSuspectedCluster(t *testing.T) {
	cfg := DefaultShadowConfig()
	now := time.Date(2026, 8, 26, 12, 0, 0, 0, time.UTC)
	a := baseReport("r-medium-a", now)
	b := baseReport("r-medium-b", now.Add(5*time.Minute))
	a.TransformerIDs = []string{"TX-A"}
	b.TransformerIDs = []string{"TX-B"}
	a.UpstreamProtectionIDs = nil
	b.UpstreamProtectionIDs = nil
	clusters := BuildConservativeClusters([]ReportEvidence{a, b}, cfg)
	if len(clusters) != 1 {
		t.Fatalf("same-feeder MEDIUM relationship should form one suspected cluster, got %#v", clusters)
	}
	if clusters[0].ConfidenceLevel != ConfidenceMedium {
		t.Fatalf("expected MEDIUM suspected cluster, got %#v", clusters[0])
	}
}
