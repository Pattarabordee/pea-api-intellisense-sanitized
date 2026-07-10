package config

import (
	"errors"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Port               int
	APIKey             string
	DatabaseURL        string
	RateLimitPerMinute int
	AllowedOrigin      string
	ProductionSendMode string
	CallbackTransport  string
	EmergencyOff        bool
}

func Load() Config {
	return Config{
		Port:               envInt("PORT", 8090),
		APIKey:             os.Getenv("AIS_INBOUND_API_KEY"),
		DatabaseURL:        os.Getenv("DATABASE_URL"),
		RateLimitPerMinute: envInt("RATE_LIMIT_PER_MINUTE", 120),
		AllowedOrigin:      os.Getenv("ALLOWED_ORIGIN"),
		ProductionSendMode: os.Getenv("PRODUCTION_SEND_MODE"),
		CallbackTransport:  os.Getenv("CALLBACK_TRANSPORT"),
		EmergencyOff:        envBool("EMERGENCY_OFF", false),
	}
}

func (c Config) Validate() error {
	if strings.TrimSpace(c.APIKey) == "" {
		return errors.New("AIS_INBOUND_API_KEY is required")
	}
	if strings.TrimSpace(c.DatabaseURL) == "" {
		return errors.New("DATABASE_URL is required")
	}
	return nil
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
