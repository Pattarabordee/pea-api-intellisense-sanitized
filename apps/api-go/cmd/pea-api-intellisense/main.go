package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"pea-api-intellisense/apps/api-go/internal/api"
	"pea-api-intellisense/apps/api-go/internal/config"
	"pea-api-intellisense/apps/api-go/internal/correlation"
	"pea-api-intellisense/apps/api-go/internal/storage"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg := config.Load()
	if err := cfg.Validate(); err != nil {
		logger.Error("invalid service configuration", "error", err)
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	store, err := storage.NewPostgresStore(ctx, cfg.DatabaseURL)
	if err != nil {
		logger.Error("postgres connect failed", "error", err)
		os.Exit(1)
	}
	defer store.Close()

	if err := store.Init(ctx); err != nil {
		logger.Error("postgres migration failed", "error", err)
		os.Exit(1)
	}

	handler := api.NewServer(api.ServerConfig{
		APIKey:                         cfg.APIKey,
		OutageIntegrationAPIKey:        cfg.OutageIntegrationAPIKey,
		RateLimitPerMinute:             cfg.RateLimitPerMinute,
		AllowedOrigin:                  cfg.AllowedOrigin,
		ProductionSendMode:             cfg.ProductionSendMode,
		CallbackTransport:              cfg.CallbackTransport,
		EmergencyOff:                   cfg.EmergencyOff,
		PlannedOutageMode:              cfg.PlannedOutageMode,
		PlannedOutageBaseURL:           cfg.PlannedOutageBaseURL,
		PlannedOutageTTLSeconds:        cfg.PlannedOutageTTLSeconds,
		PlannedOutageHotTTLSeconds:     cfg.PlannedOutageHotTTLSeconds,
		PlannedOutageTimeoutMS:         cfg.PlannedOutageTimeoutMS,
		IncidentCorrelationMode:        cfg.IncidentCorrelationMode,
		IncidentCorrelationMaxAttempts: cfg.IncidentCorrelationMaxAttempts,
		Logger:                         logger,
	}, store)

	if strings.EqualFold(strings.TrimSpace(cfg.IncidentCorrelationMode), "shadow") {
		workerID := fmt.Sprintf("correlation-%d", os.Getpid())
		worker := correlation.NewWorker(store, correlation.WorkerConfig{
			WorkerID:      workerID,
			PollInterval:  time.Duration(cfg.IncidentCorrelationPollMS) * time.Millisecond,
			LeaseDuration: time.Duration(cfg.IncidentCorrelationLeaseSeconds) * time.Second,
			SnapshotLimit: cfg.IncidentCorrelationSnapshotLimit,
			EngineConfig:  correlation.DefaultShadowConfig(),
			Logger:        logger,
		})
		go worker.Run(ctx)
		logger.Info("incident correlation shadow worker enabled",
			"engine_version", correlation.EngineVersion,
			"poll_ms", cfg.IncidentCorrelationPollMS,
			"lease_seconds", cfg.IncidentCorrelationLeaseSeconds,
			"snapshot_limit", cfg.IncidentCorrelationSnapshotLimit)
	}

	server := &http.Server{
		Addr:              ":" + strconv.Itoa(cfg.Port),
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      20 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	go func() {
		logger.Info("pea api intellisense cloud shadow api starting", "port", cfg.Port)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server failed", "error", err)
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("server shutdown failed", "error", err)
	}
}
