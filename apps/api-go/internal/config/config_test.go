package config

import "testing"

func TestValidateRequiresAPIKeyAndDatabase(t *testing.T) {
	if err := (Config{}).Validate(); err == nil {
		t.Fatal("empty configuration must be rejected")
	}
	if err := (Config{APIKey: "pilot-key"}).Validate(); err == nil {
		t.Fatal("missing database URL must be rejected")
	}
	if err := (Config{APIKey: "pilot-key", DatabaseURL: "postgres://example"}).Validate(); err != nil {
		t.Fatalf("complete configuration was rejected: %v", err)
	}
}
