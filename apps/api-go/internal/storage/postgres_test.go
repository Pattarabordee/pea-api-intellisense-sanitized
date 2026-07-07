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
