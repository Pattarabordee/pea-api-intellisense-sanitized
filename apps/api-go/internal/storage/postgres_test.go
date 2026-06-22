package storage

import (
	"encoding/json"
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
