package config

import (
	"os"
	"path/filepath"
	"testing"
)

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

func TestIncidentCorrelationWorkerEnabledDefaultsTrueAndCanDisable(t *testing.T) {
	t.Setenv("INCIDENT_CORRELATION_WORKER_ENABLED", "")
	if cfg := Load(); !cfg.IncidentCorrelationWorkerEnabled {
		t.Fatal("INCIDENT_CORRELATION_WORKER_ENABLED must default true for backward compatibility")
	}
	t.Setenv("INCIDENT_CORRELATION_WORKER_ENABLED", "false")
	if cfg := Load(); cfg.IncidentCorrelationWorkerEnabled {
		t.Fatal("INCIDENT_CORRELATION_WORKER_ENABLED=false must disable the runtime worker")
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

func TestLoadSupportsSecretFiles(t *testing.T) {
	dir := t.TempDir()
	outagePath := filepath.Join(dir, "outage.key")
	databasePath := filepath.Join(dir, "database.url")
	if err := os.WriteFile(outagePath, []byte("file-outage-key\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(databasePath, []byte("postgres://file-db\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("OUTAGE_INTEGRATION_API_KEY", "")
	t.Setenv("OUTAGE_INTEGRATION_API_KEY_FILE", outagePath)
	t.Setenv("DATABASE_URL", "")
	t.Setenv("DATABASE_URL_FILE", databasePath)
	cfg := Load()
	if cfg.OutageIntegrationAPIKey != "file-outage-key" {
		t.Fatalf("outage integration key = %q, want file value", cfg.OutageIntegrationAPIKey)
	}
	if cfg.DatabaseURL != "postgres://file-db" {
		t.Fatalf("database URL = %q, want file value", cfg.DatabaseURL)
	}
}

func TestDirectSecretEnvTakesPrecedenceOverFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "outage.key")
	if err := os.WriteFile(path, []byte("file-value"), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("OUTAGE_INTEGRATION_API_KEY", "env-value")
	t.Setenv("OUTAGE_INTEGRATION_API_KEY_FILE", path)
	if got := Load().OutageIntegrationAPIKey; got != "env-value" {
		t.Fatalf("key = %q, want direct env precedence", got)
	}
}

func TestUnreadableSecretFileFailsClosed(t *testing.T) {
	t.Setenv("OUTAGE_INTEGRATION_API_KEY", "")
	t.Setenv("OUTAGE_INTEGRATION_API_KEY_FILE", filepath.Join(t.TempDir(), "missing"))
	t.Setenv("DATABASE_URL", "postgres://example")
	cfg := Load()
	cfg.RuntimeProfile = "pea-current"
	if err := cfg.Validate(); err == nil {
		t.Fatal("unreadable secret file must fail closed through configuration validation")
	}
}
