package main

import (
	"context"
	"log/slog"
	"os"
	"strings"

	"pea-api-intellisense/apps/api-go/internal/storage"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	databaseURL := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if databaseURL == "" {
		logger.Error("DATABASE_URL is required")
		os.Exit(1)
	}
	profile := strings.TrimSpace(os.Getenv("RUNTIME_PROFILE"))
	if profile == "" {
		profile = "legacy-full"
	}
	ctx := context.Background()
	store, err := storage.NewPostgresStore(ctx, databaseURL)
	if err != nil {
		logger.Error("postgres connect failed", "error", err)
		os.Exit(1)
	}
	defer store.Close()
	if err := store.InitProfile(ctx, profile); err != nil {
		logger.Error("postgres migration failed", "runtime_profile", profile, "error", err)
		os.Exit(1)
	}
	logger.Info("postgres migrations complete", "runtime_profile", profile)
}
