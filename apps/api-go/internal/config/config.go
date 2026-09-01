package config

import (
	"errors"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	RuntimeProfile                   string
	ListenAddress                    string
	Port                             int
	APIKey                           string
	OutageIntegrationAPIKey          string
	DatabaseURL                      string
	RunDBMigrations                  bool
	RateLimitPerMinute               int
	AllowedOrigin                    string
	ProductionSendMode               string
	CallbackTransport                string
	EmergencyOff                     bool
	PlannedOutageMode                string
	PlannedOutageBaseURL             string
	PlannedOutageTTLSeconds          int
	PlannedOutageHotTTLSeconds       int
	PlannedOutageTimeoutMS           int
	IncidentCorrelationMode          string
	IncidentCorrelationWorkerEnabled bool
	IncidentCorrelationMaxAttempts   int
	IncidentCorrelationPollMS        int
	IncidentCorrelationLeaseSeconds  int
	IncidentCorrelationSnapshotLimit int
}

func Load() Config {
	return Config{
		RuntimeProfile:                   envString("RUNTIME_PROFILE", "legacy-full"),
		ListenAddress:                    os.Getenv("LISTEN_ADDRESS"),
		Port:                             envInt("PORT", 8090),
		APIKey:                           envOrFile("AIS_INBOUND_API_KEY", "AIS_INBOUND_API_KEY_FILE"),
		OutageIntegrationAPIKey:          envOrFile("OUTAGE_INTEGRATION_API_KEY", "OUTAGE_INTEGRATION_API_KEY_FILE"),
		DatabaseURL:                      envOrFile("DATABASE_URL", "DATABASE_URL_FILE"),
		RunDBMigrations:                  envBool("RUN_DB_MIGRATIONS", true),
		RateLimitPerMinute:               envInt("RATE_LIMIT_PER_MINUTE", 120),
		AllowedOrigin:                    os.Getenv("ALLOWED_ORIGIN"),
		ProductionSendMode:               os.Getenv("PRODUCTION_SEND_MODE"),
		CallbackTransport:                os.Getenv("CALLBACK_TRANSPORT"),
		EmergencyOff:                     envBool("EMERGENCY_OFF", false),
		PlannedOutageMode:                envString("PLANNED_OUTAGE_MODE", "shadow"),
		PlannedOutageBaseURL:             envString("PLANNED_OUTAGE_BASE_URL", "https://eservice.pea.co.th/PowerOutage"),
		PlannedOutageTTLSeconds:          envInt("PLANNED_OUTAGE_TTL_SECONDS", 900),
		PlannedOutageHotTTLSeconds:       envInt("PLANNED_OUTAGE_HOT_TTL_SECONDS", 300),
		PlannedOutageTimeoutMS:           envInt("PLANNED_OUTAGE_TIMEOUT_MS", 1200),
		IncidentCorrelationMode:          envString("INCIDENT_CORRELATION_MODE", "off"),
		IncidentCorrelationWorkerEnabled: envBool("INCIDENT_CORRELATION_WORKER_ENABLED", true),
		IncidentCorrelationMaxAttempts:   envInt("INCIDENT_CORRELATION_MAX_ATTEMPTS", 5),
		IncidentCorrelationPollMS:        envInt("INCIDENT_CORRELATION_POLL_MS", 1000),
		IncidentCorrelationLeaseSeconds:  envInt("INCIDENT_CORRELATION_LEASE_SECONDS", 30),
		IncidentCorrelationSnapshotLimit: envInt("INCIDENT_CORRELATION_SNAPSHOT_LIMIT", 1000),
	}
}

func (c Config) Validate() error {
	profile := strings.ToLower(strings.TrimSpace(c.RuntimeProfile))
	if profile == "" {
		profile = "legacy-full"
	}
	if profile != "legacy-full" && profile != "pea-current" {
		return errors.New("RUNTIME_PROFILE must be legacy-full or pea-current")
	}
	if profile == "legacy-full" && strings.TrimSpace(c.APIKey) == "" {
		return errors.New("AIS_INBOUND_API_KEY is required for legacy-full runtime profile")
	}
	if profile == "pea-current" && strings.TrimSpace(c.OutageIntegrationAPIKey) == "" {
		return errors.New("OUTAGE_INTEGRATION_API_KEY is required for pea-current runtime profile")
	}
	if strings.TrimSpace(c.DatabaseURL) == "" {
		return errors.New("DATABASE_URL is required")
	}
	mode := strings.ToLower(strings.TrimSpace(c.IncidentCorrelationMode))
	if mode != "" && mode != "off" && mode != "shadow" {
		return errors.New("INCIDENT_CORRELATION_MODE must be off or shadow")
	}
	return nil
}

// ListenHost preserves the legacy all-interface default while making the
// pre-cutover PEA runtime fail closed to loopback unless an operator explicitly
// supplies LISTEN_ADDRESS.
func (c Config) ListenHost() string {
	if host := strings.TrimSpace(c.ListenAddress); host != "" {
		return host
	}
	if strings.EqualFold(strings.TrimSpace(c.RuntimeProfile), "pea-current") {
		return "127.0.0.1"
	}
	return ""
}

func envOrFile(name, fileName string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	path := strings.TrimSpace(os.Getenv(fileName))
	if path == "" {
		return ""
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

func envString(name, fallback string) string {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	return value
}

func envInt(name string, fallback int) int {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}

func envBool(name string, fallback bool) bool {
	value := os.Getenv(name)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseBool(value)
	if err != nil {
		return fallback
	}
	return parsed
}
