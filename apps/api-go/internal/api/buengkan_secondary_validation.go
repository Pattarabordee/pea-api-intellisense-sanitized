package api

import (
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"pea-api-intellisense/apps/api-go/internal/buengkan"
	"pea-api-intellisense/apps/api-go/internal/storage"
)

const (
	buengKanSecondaryValidationPath = "/api/v1/buengkan/secondary-validation"
	buengKanSecondaryValidationCatalogPath = "/api/v1/buengkan/secondary-validation/catalog"
)

type secondaryValidationRequest struct {
	ReceiptID string `json:"receipt_id"`
	SourceType string `json:"source_type"`
	SourceRef string `json:"source_ref"`
	ValidatorRef string `json:"validator_ref"`
	Verdict string `json:"verdict"`
	SelectedTransformer string `json:"selected_transformer"`
	CorrectionTransformer string `json:"correction_transformer"`
	CorrectionFeeder string `json:"correction_feeder"`
}

func (s *Server) handleBuengKanSecondaryValidationCatalog(w http.ResponseWriter, r *http.Request) {
	if !s.authorized(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"api_version": APIVersion,
		"mode": Mode,
		"production_send": ProductionSend,
		"catalog": buengkan.ValidationCatalogPayload(),
		"generated_at": nowISO(),
	})
}

func (s *Server) handleBuengKanSecondaryValidationPost(w http.ResponseWriter, r *http.Request) {
	if !s.authorized(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	defer r.Body.Close()
	decoder := json.NewDecoder(io.LimitReader(r.Body, 32_000))
	decoder.DisallowUnknownFields()
	var input secondaryValidationRequest
	if err := decoder.Decode(&input); err != nil {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_VALIDATION", "Invalid secondary validation payload", ""))
		return
	}
	input.ReceiptID = strings.TrimSpace(input.ReceiptID)
	input.SourceType = strings.ToUpper(strings.TrimSpace(input.SourceType))
	input.SourceRef = strings.TrimSpace(input.SourceRef)
	input.ValidatorRef = strings.TrimSpace(input.ValidatorRef)
	input.Verdict = strings.ToUpper(strings.TrimSpace(input.Verdict))
	input.SelectedTransformer = strings.ToUpper(strings.TrimSpace(input.SelectedTransformer))
	input.CorrectionTransformer = strings.ToUpper(strings.TrimSpace(input.CorrectionTransformer))
	input.CorrectionFeeder = strings.ToUpper(strings.TrimSpace(input.CorrectionFeeder))
	if !safeID.MatchString(input.ReceiptID) || !safeID.MatchString(input.SourceRef) || !safeID.MatchString(input.ValidatorRef) {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_VALIDATION_ID", "receipt_id, source_ref, or validator_ref is invalid", ""))
		return
	}
	if input.SourceType != "POI" && input.SourceType != "ROAD_SOI" {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_SOURCE_TYPE", "source_type must be POI or ROAD_SOI", ""))
		return
	}
	if input.Verdict != "CORRECT" && input.Verdict != "INCORRECT" && input.Verdict != "UNSURE" {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_VERDICT", "verdict must be CORRECT, INCORRECT, or UNSURE", ""))
		return
	}
	for _, value := range []string{input.SelectedTransformer, input.CorrectionTransformer, input.CorrectionFeeder} {
		if value != "" && !safeID.MatchString(value) {
			writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_VALIDATION_FIELD", "validation identifier contains unsupported characters", ""))
			return
		}
	}
	item, err := buengkan.ValidationCatalogItemByRef(input.SourceRef)
	if err != nil || item.SourceType != input.SourceType {
		writeJSON(w, http.StatusBadRequest, errorPayload("UNKNOWN_VALIDATION_SOURCE", "source_ref is not in the approved validation catalog", ""))
		return
	}
	if input.SelectedTransformer != "" && !buengkan.ValidationCatalogHasCandidate(item, input.SelectedTransformer) {
		writeJSON(w, http.StatusBadRequest, errorPayload("INVALID_SELECTED_TRANSFORMER", "selected_transformer must be one of the catalog candidates", ""))
		return
	}
	if input.Verdict == "CORRECT" {
		if input.SelectedTransformer == "" && len(item.Candidates) == 1 {
			input.SelectedTransformer = item.Candidates[0].FacilityID
		}
		if len(item.Candidates) > 1 && input.SelectedTransformer == "" {
			writeJSON(w, http.StatusBadRequest, errorPayload("SELECTED_TRANSFORMER_REQUIRED", "ambiguous source requires selecting the field-confirmed transformer", ""))
			return
		}
		if len(item.Candidates) == 0 {
			writeJSON(w, http.StatusBadRequest, errorPayload("NO_CANDIDATE_TO_CONFIRM", "source has no transformer candidate to confirm", ""))
			return
		}
	}
	candidateIDs := make([]string, 0, len(item.Candidates))
	for _, candidate := range item.Candidates { candidateIDs = append(candidateIDs, candidate.FacilityID) }
	candidateJSON, _ := json.Marshal(candidateIDs)
	duplicate, err := s.store.InsertBuengKanSecondaryValidation(r.Context(), storage.BuengKanSecondaryValidation{
		ReceiptID: input.ReceiptID,
		RecordedAt: time.Now().UTC(),
		SourceType: item.SourceType,
		SourceRef: item.SourceRef,
		SourceLabel: item.Label,
		ValidatorRef: input.ValidatorRef,
		Priority: item.Priority,
		Verdict: input.Verdict,
		CandidateTransformers: candidateJSON,
		SelectedTransformer: input.SelectedTransformer,
		CorrectionTransformer: input.CorrectionTransformer,
		CorrectionFeeder: input.CorrectionFeeder,
		Mode: Mode,
		ProductionSend: ProductionSend,
	})
	if err != nil {
		s.cfg.Logger.Error("buengkan secondary validation insert failed", "source_ref", item.SourceRef, "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not persist secondary validation", ""))
		return
	}
	status := http.StatusCreated
	if duplicate { status = http.StatusOK }
	writeJSON(w, status, map[string]any{
		"api_version": APIVersion,
		"mode": Mode,
		"production_send": ProductionSend,
		"status": "STORED_FOR_REVIEW",
		"receipt_id": input.ReceiptID,
		"source_ref": item.SourceRef,
		"verdict": input.Verdict,
		"selected_transformer": input.SelectedTransformer,
		"duplicate": duplicate,
		"auto_promoted": false,
		"generated_at": nowISO(),
	})
}

func (s *Server) handleBuengKanSecondaryValidationList(w http.ResponseWriter, r *http.Request) {
	if !s.authorized(r) {
		writeJSON(w, http.StatusUnauthorized, errorPayload("UNAUTHORIZED", "X-API-Key or Authorization Bearer credential is required", ""))
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 2000 { limit = 500 }
	rows, err := s.store.ListBuengKanSecondaryValidation(r.Context(), limit)
	if err != nil {
		s.cfg.Logger.Error("buengkan secondary validation list failed", "error", err)
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load secondary validations", ""))
		return
	}
	counts, err := s.store.BuengKanSecondaryValidationCounts(r.Context())
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, errorPayload("INTERNAL_ERROR", "Could not load secondary validation counts", ""))
		return
	}
	items := make([]map[string]any, 0, len(rows))
	for _, row := range rows {
		candidates := []string{}
		_ = json.Unmarshal(row.CandidateTransformers, &candidates)
		items = append(items, map[string]any{
			"receipt_id": row.ReceiptID,
			"recorded_at": row.RecordedAt.UTC().Format(time.RFC3339),
			"source_type": row.SourceType,
			"source_ref": row.SourceRef,
			"source_label": row.SourceLabel,
			"validator_ref": row.ValidatorRef,
			"priority": row.Priority,
			"verdict": row.Verdict,
			"candidate_transformers": candidates,
			"selected_transformer": row.SelectedTransformer,
			"correction_transformer": row.CorrectionTransformer,
			"correction_feeder": row.CorrectionFeeder,
		})
	}
	latest := ""
	if counts.LatestAt != nil { latest = counts.LatestAt.UTC().Format(time.RFC3339) }
	writeJSON(w, http.StatusOK, map[string]any{
		"api_version": APIVersion,
		"mode": Mode,
		"production_send": ProductionSend,
		"count": len(items),
		"items": items,
		"summary": map[string]any{"total": counts.Total, "correct": counts.Correct, "incorrect": counts.Incorrect, "unsure": counts.Unsure, "latest_at": latest},
		"auto_promotion": false,
		"generated_at": nowISO(),
	})
}
