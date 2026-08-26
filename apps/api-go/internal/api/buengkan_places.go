package api

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"strconv"
	"unicode"
	"unicode/utf8"
	"time"

	"pea-api-intellisense/apps/api-go/internal/storage"

	"pea-api-intellisense/apps/api-go/internal/buengkan"
)

const (
	placeDiscoveryQueuePath = "/api/v1/places/discovery-queue"
	placeResolvePath      = "/api/v1/places/resolve"
	placePathPrefix       = "/api/v1/places/"
	placeResolveSchema    = "place-resolve.v1"
	placeResolutionSchema = "place-resolution.v1"
	placeAssetSchema      = "place.v1"
)

type placeLocationInput struct {
	Lat       *float64 `json:"lat"`
	Lon       *float64 `json:"lon"`
	AccuracyM *float64 `json:"accuracy_m"`
	Source    string   `json:"source"`
}

type placeResolveRequest struct {
	SchemaVersion string              `json:"schema_version"`
	Query         string              `json:"query"`
	Location      *placeLocationInput `json:"location"`
	Limit         int                 `json:"limit"`
}

func (s *Server) handlePlaceResolve(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	if ok, retryAfter := s.limiter.allow(clientIP(r)); !ok {
		w.Header().Set("Retry-After", strconvItoa(retryAfter))
		writeJSON(w, http.StatusTooManyRequests, errorPayload("RATE_LIMITED", "Too many requests. Retry later.", ""))
		return
	}
	if !strings.Contains(strings.ToLower(r.Header.Get("Content-Type")), "application/json") {
		writeJSON(w, http.StatusUnsupportedMediaType, errorPayload("UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json", ""))
		return
	}
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, 64_000))
	decoder.DisallowUnknownFields()
	var input placeResolveRequest
	if err := decoder.Decode(&input); err != nil {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_REQUEST", "Request body must match place-resolve.v1 JSON schema", ""))
		return
	}
	if err := validatePlaceResolveRequest(&input); err != nil {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_REQUEST", err.Error(), ""))
		return
	}
	var location *buengkan.PlaceResolveLocationInput
	if input.Location != nil {
		location = &buengkan.PlaceResolveLocationInput{
			Lat: *input.Location.Lat, Lon: *input.Location.Lon, AccuracyM: input.Location.AccuracyM, Source: strings.TrimSpace(input.Location.Source),
		}
	}
	result := buengkan.ResolvePlace(input.Query, location, input.Limit)
	if result.MatchCount == 0 {
		if err := s.recordUnknownPlaceObservation(r, input.Query, location, "PLACE_API", ""); err != nil {
			s.cfg.Logger.Error("unknown place queue insert failed", "query_ref", hashReference("place_query", input.Query), "error", err)
			result.DiscoveryStatus = "QUEUE_WRITE_FAILED"
		} else {
			result.DiscoveryStatus = "QUEUED_HASH_ONLY"
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"api_version":       APIVersion,
		"schema_version":    placeResolutionSchema,
		"gazetteer_version": buengkan.PlaceGazetteerVersion,
		"gazetteer_count":   buengkan.PlaceGazetteerCount(),
		"mode":              Mode,
		"production_send":   ProductionSend,
		"resolver":          result,
		"generated_at":      nowISO(),
	})
}

func (s *Server) handlePlaceLookup(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	placeID, err := url.PathUnescape(strings.TrimPrefix(r.URL.Path, placePathPrefix))
	placeID = strings.TrimSpace(placeID)
	if err != nil || len(placeID) != 23 || !strings.HasPrefix(placeID, "plc_bk_") || strings.Contains(placeID, "/") || !safeID.MatchString(placeID) {
		writeJSON(w, http.StatusNotFound, errorPayload("PLACE_NOT_FOUND", "Place was not found in the approved gazetteer", ""))
		return
	}
	place, err := buengkan.LookupPlace(placeID)
	if err != nil {
		writeJSON(w, http.StatusNotFound, errorPayload("PLACE_NOT_FOUND", "Place was not found in the approved gazetteer", ""))
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"api_version":       APIVersion,
		"schema_version":    placeAssetSchema,
		"gazetteer_version": buengkan.PlaceGazetteerVersion,
		"mode":              Mode,
		"production_send":   ProductionSend,
		"place":             place,
		"generated_at":      nowISO(),
	})
}

func validatePlaceResolveRequest(input *placeResolveRequest) error {
	if input.SchemaVersion != "" && input.SchemaVersion != placeResolveSchema {
		return errors.New("schema_version must be place-resolve.v1")
	}
	query := strings.TrimSpace(input.Query)
	if utf8.RuneCountInString(query) == 0 || utf8.RuneCountInString(query) > 1000 {
		return errors.New("query is required and must be <= 1000 characters")
	}
	for _, r := range query {
		if unicode.IsControl(r) && r != '\n' && r != '\r' && r != '\t' {
			return errors.New("query must not contain control characters")
		}
	}
	if input.Limit < 0 || input.Limit > 25 {
		return errors.New("limit must be between 1 and 25 when provided")
	}
	if input.Location != nil {
		if input.Location.Lat == nil || input.Location.Lon == nil || *input.Location.Lat < -90 || *input.Location.Lat > 90 || *input.Location.Lon < -180 || *input.Location.Lon > 180 {
			return errors.New("location.lat/lon must be valid WGS84 coordinates")
		}
		if input.Location.AccuracyM != nil && (*input.Location.AccuracyM < 0 || *input.Location.AccuracyM > 100000) {
			return errors.New("location.accuracy_m must be between 0 and 100000")
		}
		if utf8.RuneCountInString(input.Location.Source) > 64 {
			return errors.New("location.source must be <= 64 characters")
		}
	}
	return nil
}

func (s *Server) handlePlaceDiscoveryQueue(w http.ResponseWriter, r *http.Request) {
	if !s.authorizedOutage(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 500 { limit = 100 }
	items, err := s.store.ListBuengKanUnknownPlaceQueue(r.Context(), limit)
	if err != nil {
		s.cfg.Logger.Error("unknown place queue list failed", "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load place discovery queue", ""))
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"api_version": APIVersion,
		"schema_version": "place-discovery-queue.v1",
		"mode": Mode,
		"production_send": ProductionSend,
		"raw_query_persisted": false,
		"auto_add": false,
		"items": items,
		"count": len(items),
		"generated_at": nowISO(),
	})
}

func (s *Server) recordUnknownPlaceObservation(r *http.Request, query string, location *buengkan.PlaceResolveLocationInput, sourceChannel, eventID string) error {
	queryHash := hashCompact("place_query", buengkan.NormalizeText(query))
	if queryHash == "" { return nil }
	cell := ""
	if location != nil && location.Lat >= -90 && location.Lat <= 90 && location.Lon >= -180 && location.Lon <= 180 {
		cell = fmt.Sprintf("%.3f,%.3f", location.Lat, location.Lon)
	}
	basis := strings.ToUpper(strings.TrimSpace(sourceChannel)) + "|" + queryHash + "|" + cell
	if strings.TrimSpace(eventID) != "" {
		basis += "|event:" + hashCompact("unknown_place_event", eventID)
	} else {
		basis += "|day:" + time.Now().UTC().Format("2006-01-02")
	}
	sum := sha256.Sum256([]byte(basis))
	observationHash := hex.EncodeToString(sum[:])[:24]
	_, err := s.store.RecordBuengKanUnknownPlaceObservation(r.Context(), storage.BuengKanUnknownPlaceObservation{
		ObservationHash: observationHash,
		QueryHash: queryHash,
		LocationCell: cell,
		SourceChannel: strings.ToUpper(strings.TrimSpace(sourceChannel)),
		SeenAt: time.Now().UTC(),
		Mode: Mode,
		ProductionSend: ProductionSend,
	})
	return err
}
