package storage

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"
)

func TestCallbackOutboxInsertArgsKeepEmptyLastErrorAsText(t *testing.T) {
	now := time.Date(2026, 6, 22, 4, 20, 31, 0, time.UTC)
	args := callbackOutboxInsertArgs(42, CallbackOutbox{
		RequestID:      "AIS-TEST",
		PayloadHash:    "hash",
		PayloadJSON:    json.RawMessage(`{}`),
		Transport:      "dry_run",
		Status:         "DRY_RUN_HELD",
		MaxAttempts:    5,
		LastError:      "",
		ProductionSend: "blocked",
		CreatedAt:      now,
		UpdatedAt:      now,
	})

	lastError, ok := args[8].(string)
	if !ok {
		t.Fatalf("callback_outbox last_error arg must be text, got %T", args[8])
	}
	if lastError != "" {
		t.Fatalf("empty last_error must stay empty string, got %q", lastError)
	}
}

func TestTruthIntervalIDUsesMeterState(t *testing.T) {
	outageAt := time.Date(2026, 7, 7, 1, 0, 0, 0, time.UTC)
	truth := TruthObservation{
		RequestID: "OUT-1",
		SiteHash:  "site-hash",
		MeterHash: "meter-hash",
	}

	id1 := truthIntervalID(truth, outageAt)
	id2 := truthIntervalID(truth, outageAt)

	if id1 != id2 {
		t.Fatalf("interval id should be deterministic: %s != %s", id1, id2)
	}
	if !strings.HasPrefix(id1, "ais-") || len(id1) != 24 {
		t.Fatalf("unexpected interval id shape: %s", id1)
	}
	if truthPairKey(truth) != "meter-hash" {
		t.Fatalf("meter hash must be the state key")
	}
}

func TestTruthPairKeyFallsBackToMeter(t *testing.T) {
	truth := TruthObservation{MeterHash: "meter-hash"}
	if truthPairKey(truth) != "meter-hash" {
		t.Fatalf("meter hash should be fallback pair key")
	}
}

func TestTruthCorrelationHashIsStableAndDoesNotContainSourceID(t *testing.T) {
	truth := TruthObservation{SourceEventHash: "source_event_abcdef"}
	first := truthCorrelationHash(truth)
	second := truthCorrelationHash(truth)

	if first == "" || first != second {
		t.Fatalf("correlation hash must be deterministic and non-empty: %q %q", first, second)
	}
	if first != truth.SourceEventHash {
		t.Fatalf("stored correlation reference must already be hashed: %s", first)
	}
	if truthCorrelationHash(TruthObservation{}) != "" {
		t.Fatal("missing source event id must not produce a correlation hash")
	}
}

func TestStrictModelDurationBoundaries(t *testing.T) {
	for _, test := range []struct {
		minutes float64
		want    bool
	}{
		{minutes: 5, want: false},
		{minutes: 5.001, want: true},
		{minutes: 1440, want: true},
		{minutes: 1440.001, want: false},
	} {
		if got := strictModelDuration(test.minutes); got != test.want {
			t.Fatalf("strictModelDuration(%v) = %v, want %v", test.minutes, got, test.want)
		}
	}
}

func TestStrictRestoreOutcomeRejectsMissingOrAmbiguousIdentityBridge(t *testing.T) {
	now := time.Date(2026, 7, 10, 1, 0, 0, 0, time.UTC)
	if got := strictRestoreOutcome(0, time.Time{}, now); got.validationStatus != "REVIEW_NO_OPEN_INTERVAL" {
		t.Fatalf("missing open interval must be review-only: %#v", got)
	}
	if got := strictRestoreOutcome(2, now.Add(-time.Hour), now); got.validationStatus != "REVIEW_MULTIPLE_OPEN_INTERVALS" {
		t.Fatalf("multiple open intervals must be an identity conflict: %#v", got)
	}
}

func TestStrictRestoreOutcomeRequiresTimeOrderAndValidDuration(t *testing.T) {
	outageAt := time.Date(2026, 7, 10, 1, 0, 0, 0, time.UTC)
	if got := strictRestoreOutcome(1, outageAt, outageAt); got.validationStatus != "REVIEW_RESTORE_BEFORE_OUTAGE" {
		t.Fatalf("restore at outage time must be review-only: %#v", got)
	}
	if got := strictRestoreOutcome(1, outageAt, outageAt.Add(5*time.Minute)); got.validationStatus != "REVIEW_DURATION_OUT_OF_RANGE" || got.bridgeStatus != "METER_STATE_DURATION_REVIEW" {
		t.Fatalf("short strict pair must remain duration review: %#v", got)
	}
	if got := strictRestoreOutcome(1, outageAt, outageAt.Add(60*time.Minute)); got.validationStatus != "READY_FOR_LEDGER" || got.bridgeStatus != "METER_STATE_MODEL_READY" || got.pairStatus != "CLOSED" {
		t.Fatalf("valid strict pair must be model-ready: %#v", got)
	}
}

func TestRestoreV2MigrationQuarantinesV1WithoutRewritingHistoricalEvents(t *testing.T) {
	sqlBytes, err := migrationFS.ReadFile("migrations/007_restore_semantic_v2_activation.sql")
	if err != nil {
		t.Fatal(err)
	}
	sql := string(sqlBytes)
	for _, required := range []string{
		"REVIEW_PREACTIVATION_PAIR",
		"REVIEW_PREACTIVATION_OPEN",
		"REVIEW_STALE_PREACTIVATION_OPEN",
		"ais_truth_interval_status_audit",
		"semantic_mapping_version",
		"ON CONFLICT (interval_id, new_bridge_status, semantic_mapping_version) DO NOTHING",
	} {
		if !strings.Contains(sql, required) {
			t.Fatalf("migration 007 missing %q", required)
		}
	}
	upper := strings.ToUpper(sql)
	if strings.Contains(upper, "UPDATE AIS_TRUTH_LEDGER SET EVENT_TYPE") || strings.Contains(upper, "UPDATE AIS_TRUTH_LEDGER\nSET EVENT_TYPE") {
		t.Fatal("migration must not rewrite historical ledger event types")
	}
}

func TestMeterOpenIntervalQueryRequiresSameMappingVersion(t *testing.T) {
	sourceBytes, err := migrationFS.ReadFile("migrations/007_restore_semantic_v2_activation.sql")
	if err != nil || len(sourceBytes) == 0 {
		t.Fatal("migration 007 must be embedded")
	}
	const requiredPredicate = "AND semantic_mapping_version = $2"
	postgresSource, err := os.ReadFile("postgres.go")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(postgresSource), requiredPredicate) {
		t.Fatal("meter-state pairing must reject cross-version intervals")
	}
}
