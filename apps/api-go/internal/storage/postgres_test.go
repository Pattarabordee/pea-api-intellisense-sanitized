package storage

import (
	"encoding/json"
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

func TestTruthIntervalIDUsesSiteWhenPresent(t *testing.T) {
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
	if truthPairKey(truth) != "site-hash" {
		t.Fatalf("site hash should be preferred as pair key")
	}
}

func TestTruthPairKeyFallsBackToMeter(t *testing.T) {
	truth := TruthObservation{MeterHash: "meter-hash"}
	if truthPairKey(truth) != "meter-hash" {
		t.Fatalf("meter hash should be fallback pair key")
	}
}

func TestTruthCorrelationHashIsStableAndDoesNotContainSourceID(t *testing.T) {
	truth := TruthObservation{SourceEventID: "SRC-SECRET-1001"}
	first := truthCorrelationHash(truth)
	second := truthCorrelationHash(truth)

	if first == "" || first != second {
		t.Fatalf("correlation hash must be deterministic and non-empty: %q %q", first, second)
	}
	if strings.Contains(first, truth.SourceEventID) {
		t.Fatalf("correlation hash leaked source event id: %s", first)
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
	if got := strictRestoreOutcome(0, time.Time{}, now); got.validationStatus != "REVIEW_NO_MATCHING_OPEN_INTERVAL" {
		t.Fatalf("missing open interval must be review-only: %#v", got)
	}
	if got := strictRestoreOutcome(2, now.Add(-time.Hour), now); got.validationStatus != "REVIEW_IDENTITY_CONFLICT" {
		t.Fatalf("multiple open intervals must be an identity conflict: %#v", got)
	}
}

func TestStrictRestoreOutcomeRequiresTimeOrderAndValidDuration(t *testing.T) {
	outageAt := time.Date(2026, 7, 10, 1, 0, 0, 0, time.UTC)
	if got := strictRestoreOutcome(1, outageAt, outageAt); got.validationStatus != "REVIEW_RESTORE_BEFORE_OUTAGE" {
		t.Fatalf("restore at outage time must be review-only: %#v", got)
	}
	if got := strictRestoreOutcome(1, outageAt, outageAt.Add(5*time.Minute)); got.validationStatus != "REVIEW_DURATION_OUT_OF_RANGE" || got.bridgeStatus != "STRICT_DURATION_REVIEW" {
		t.Fatalf("short strict pair must remain duration review: %#v", got)
	}
	if got := strictRestoreOutcome(1, outageAt, outageAt.Add(60*time.Minute)); got.validationStatus != "READY_FOR_LEDGER" || got.bridgeStatus != "STRICT_MODEL_READY" || got.pairStatus != "CLOSED" {
		t.Fatalf("valid strict pair must be model-ready: %#v", got)
	}
}
