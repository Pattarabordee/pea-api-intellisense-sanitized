package config

import (
	"errors"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Port                             int
	APIKey                           string
	OutageIntegrationAPIKey          string
	DatabaseURL                      string
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
	IncidentCorrelationMaxAttempts   int
	IncidentCorrelationPollMS        int
	IncidentCorrelationLeaseSeconds  int
	IncidentCorrelationSnapshotLimit int
}

func Load() Config {
	return Config{
		Port:                             envInt("PORT", 8090),
		APIKey:                           os.Getenv("AIS_INBOUND_API_KEY"),
		OutageIntegrationAPIKey:          os.Getenv("OUTAGE_INTEGRATION_API_KEY"),
		DatabaseURL:                      os.Getenv("DATABASE_URL"),
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
		IncidentCorrelationMaxAttempts:   envInt("INCIDENT_CORRELATION_MAX_ATTEMPTS", 5),
		IncidentCorrelationPollMS:        envInt("INCIDENT_CORRELATION_POLL_MS", 1000),
		IncidentCorrelationLeaseSeconds:  envInt("INCIDENT_CORRELATION_LEASE_SECONDS", 30),
		IncidentCorrelationSnapshotLimit: envInt("INCIDENT_CORRELATION_SNAPSHOT_LIMIT", 1000),
	}
}

func (c Config) Validate() error {
	if strings.TrimSpace(c.APIKey) == "" {
		return errors.New("AIS_INBOUND_API_KEY is required")
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
