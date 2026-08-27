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

func TestValidatePEACurrentRequiresOutageIntegrationKey(t *testing.T) {
	cfg := Config{RuntimeProfile: "pea-current", OutageIntegrationAPIKey: "outage-key", DatabaseURL: "postgres://example"}
	if err := cfg.Validate(); err != nil {
		t.Fatalf("pea-current configuration was rejected: %v", err)
	}
	cfg.OutageIntegrationAPIKey = ""
	if err := cfg.Validate(); err == nil {
		t.Fatal("pea-current must require OUTAGE_INTEGRATION_API_KEY")
	}
	cfg.RuntimeProfile = "unknown"
	if err := cfg.Validate(); err == nil {
		t.Fatal("unknown runtime profile must be rejected")
	}
}

func TestLoadRunDBMigrationsDefaultsTrueAndCanDisable(t *testing.T) {
	t.Setenv("RUN_DB_MIGRATIONS", "")
	if cfg := Load(); !cfg.RunDBMigrations {
		t.Fatal("RUN_DB_MIGRATIONS must default true for backward compatibility")
	}
	t.Setenv("RUN_DB_MIGRATIONS", "false")
	if cfg := Load(); cfg.RunDBMigrations {
		t.Fatal("RUN_DB_MIGRATIONS=false must disable runtime migrations")
	}
}

func TestListenHostDefaultsPEACurrentToLoopback(t *testing.T) {
	if got := (Config{RuntimeProfile: "pea-current"}).ListenHost(); got != "127.0.0.1" {
		t.Fatalf("pea-current listen host = %q, want loopback", got)
	}
	if got := (Config{RuntimeProfile: "legacy-full"}).ListenHost(); got != "" {
		t.Fatalf("legacy-full listen host = %q, want existing all-interface default", got)
	}
	if got := (Config{RuntimeProfile: "pea-current", ListenAddress: " 127.0.0.2 "}).ListenHost(); got != "127.0.0.2" {
		t.Fatalf("explicit listen host = %q, want trimmed override", got)
	}
}
