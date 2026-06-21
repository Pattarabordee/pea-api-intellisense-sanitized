package config

import (
	"os"
	"strconv"
)

type Config struct {
	Port               int
	APIKey             string
	DatabaseURL        string
	RateLimitPerMinute int
	AllowedOrigin      string
}

func Load() Config {
	return Config{
		Port:               envInt("PORT", 8090),
		APIKey:             os.Getenv("AIS_INBOUND_API_KEY"),
		DatabaseURL:        os.Getenv("DATABASE_URL"),
		RateLimitPerMinute: envInt("RATE_LIMIT_PER_MINUTE", 120),
		AllowedOrigin:      os.Getenv("ALLOWED_ORIGIN"),
	}
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
