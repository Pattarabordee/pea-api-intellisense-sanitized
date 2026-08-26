package api

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"pea-api-intellisense/apps/api-go/internal/storage"
)

const (
	plannedOutageModeOff         = "off"
	plannedOutageModeShadow      = "shadow"
	plannedOutageModeEnforcement = "enforcement"
	plannedOutageSourcePrimary   = "ESERVICE_READ_ONLY_ENDPOINT"
	plannedOutageSourceFallback  = "PUBLIC_PAGE_FALLBACK"
)

var plannedOutageDatePattern = regexp.MustCompile(`^/Date\((-?[0-9]+)\)/$`)
var plannedOutageMooPattern = regexp.MustCompile(`(?i)(?:หมู่|ม\.)\s*[0-9]{1,2}`)

type plannedOutageSourceRecord struct {
	Region             int    `json:"REGION"`
	Area               string `json:"AREA"`
	ProvinceID         int    `json:"PROVINCE_ID"`
	Province           string `json:"PROVINCE"`
	OfficeID           string `json:"OFFICE_ID"`
	PEAOffice          string `json:"PEA_OFFICE"`
	Detail             string `json:"DETAIL"`
	StartDate          string `json:"START_DATE"`
	EndDate            string `json:"END_DATE"`
	ExpiredDate        string `json:"EXPIRED_DATE"`
	OutageID           string `json:"OUTAGE_ID"`
	StartDateDisplay   string `json:"START_DATE_DISPLAY"`
	EndDateDisplay     string `json:"END_DATE_DISPLAY"`
	ExpiredDateDisplay string `json:"EXPIRED_DATE_DISPLAY"`
}

type plannedOutageListResponse struct {
	Draw            string                      `json:"draw"`
	RecordsFiltered int                         `json:"recordsFiltered"`
	RecordsTotal    int                         `json:"recordsTotal"`
	Data            []plannedOutageSourceRecord `json:"data"`
}

type plannedOutageNotice struct {
	ID            string    `json:"notice_id"`
	Province      string    `json:"province"`
	Area          string    `json:"area_text"`
	Detail        string    `json:"reason_text_original"`
	ReasonCode    string    `json:"reason_code"`
	Start         time.Time `json:"planned_start"`
	End           time.Time `json:"planned_end"`
	OfficeID      string    `json:"office_id,omitempty"`
	PEAOffice     string    `json:"pea_office,omitempty"`
	RevisionHash  string    `json:"notice_revision_hash"`
	SourceRef     string    `json:"source_reference"`
	PartialArea   bool      `json:"partial_area"`
	LocationMatch bool      `json:"location_match"`
	AdminMatch    bool      `json:"admin_match"`
	TimeRelation  string    `json:"time_relation"`
	EvidenceLevel string    `json:"evidence_level"`
}

type plannedOutageSnapshot struct {
	Records    []plannedOutageSourceRecord
	FetchedAt  time.Time
	SourceHash string
	SourceMode string
}

type plannedOutageCache struct {
	snapshot plannedOutageSnapshot
}

type plannedOutageCheck struct {
	Decision           string
	SourceMode         string
	SourceFetchedAt    *time.Time
	SourceHash         string
	SourceStale        bool
	NoticeID           string
	NoticeRevisionHash string
	Evidence           map[string]any
	RawSnapshot        json.RawMessage
	RawExpiresAt       *time.Time
	RelevantHash       string
}

type plannedOutageGate struct {
	mode       string
	baseURL    string
	normalTTL  time.Duration
	hotTTL     time.Duration
	httpClient *http.Client
	store      storage.Store

	mu      sync.Mutex
	fetchMu sync.Mutex
	cache   plannedOutageCache
}

func normalizePlannedOutageMode(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case plannedOutageModeShadow:
		return plannedOutageModeShadow
	case plannedOutageModeEnforcement:
		return plannedOutageModeEnforcement
	default:
		return plannedOutageModeOff
	}
}

func newPlannedOutageGate(cfg ServerConfig, store storage.Store) *plannedOutageGate {
	mode := normalizePlannedOutageMode(cfg.PlannedOutageMode)
	if mode == plannedOutageModeOff {
		return nil
	}
	baseURL := strings.TrimRight(strings.TrimSpace(cfg.PlannedOutageBaseURL), "/")
	if baseURL == "" {
		baseURL = "https://eservice.pea.co.th/PowerOutage"
	}
	normalTTL := time.Duration(cfg.PlannedOutageTTLSeconds) * time.Second
	if normalTTL <= 0 {
		normalTTL = 15 * time.Minute
	}
	hotTTL := time.Duration(cfg.PlannedOutageHotTTLSeconds) * time.Second
	if hotTTL <= 0 {
		hotTTL = 5 * time.Minute
	}
	timeout := time.Duration(cfg.PlannedOutageTimeoutMS) * time.Millisecond
	if timeout <= 0 {
		timeout = 1200 * time.Millisecond
	}
	return &plannedOutageGate{
		mode:       mode,
		baseURL:    baseURL,
		normalTTL:  normalTTL,
		hotTTL:     hotTTL,
		httpClient: &http.Client{Timeout: timeout},
		store:      store,
	}
}

func (g *plannedOutageGate) checkAndPersist(ctx context.Context, input chatbotReportRequest) plannedOutageCheck {
	occurredAt, err := time.Parse(time.RFC3339, strings.TrimSpace(input.Source.OccurredAt))
	if err != nil {
		return plannedOutageCheck{Decision: "UNAVAILABLE", Evidence: map[string]any{"reason": "invalid_occurred_at_after_contract_validation"}}
	}
	result := g.check(ctx, input.Report.Location, occurredAt)
	decisionHash := plannedOutageDecisionHash(input.Report.TicketID, result)
	latest, latestErr := g.store.GetLatestPlannedOutageDecision(ctx, input.Report.TicketID)
	sourceChanged := latestErr == nil && latest.DecisionHash != "" && latest.DecisionHash != decisionHash
	if sourceChanged {
		result.Evidence["source_changed"] = true
		result.Evidence["previous_notice_revision_hash"] = latest.NoticeRevisionHash
	}
	record := storage.PlannedOutageDecision{
		TicketID:             input.Report.TicketID,
		DecisionHash:         decisionHash,
		RecordedAt:           time.Now().UTC(),
		OccurredAt:           occurredAt.UTC(),
		SessionRefHash:       hashReference("chatbot_session", input.Source.SessionRef),
		Province:             strings.TrimSpace(input.Report.Location.Province),
		District:             strings.TrimSpace(input.Report.Location.District),
		Subdistrict:          strings.TrimSpace(input.Report.Location.Subdistrict),
		LocationText:         strings.TrimSpace(input.Report.Location.HouseOrVillage),
		Decision:             result.Decision,
		SourceMode:           result.SourceMode,
		SourceFetchedAt:      result.SourceFetchedAt,
		SourceHash:           result.SourceHash,
		SourceStale:          result.SourceStale,
		SourceChanged:        sourceChanged,
		NoticeID:             result.NoticeID,
		NoticeRevisionHash:   result.NoticeRevisionHash,
		EvidenceJSON:         mustJSON(result.Evidence),
		RawSnapshotJSON:      result.RawSnapshot,
		RawSnapshotExpiresAt: result.RawExpiresAt,
		Mode:                 g.mode,
		ProductionSend:       ProductionSend,
	}
	if _, err := g.store.InsertPlannedOutageDecision(ctx, record); err != nil {
		result.Evidence["audit_persist_error"] = true
	}
	return result
}
func (g *plannedOutageGate) check(ctx context.Context, location chatbotLocationInput, occurredAt time.Time) plannedOutageCheck {
	snapshot, fromCache, staleSnapshot, err := g.snapshot(ctx, location, occurredAt, false)
	if err != nil {
		evidence := map[string]any{
			"source":              "pea_eservice_power_outage",
			"source_mode":         plannedOutageSourcePrimary,
			"reason":              "source_unavailable_after_retry_and_public_page_fallback",
			"source_error_class":  plannedOutageErrorClass(err),
			"deterministic_only":  true,
			"ai_decision_allowed": false,
		}
		result := plannedOutageCheck{Decision: "UNAVAILABLE", SourceMode: plannedOutageSourcePrimary, SourceStale: staleSnapshot.SourceHash != "", Evidence: evidence}
		if staleSnapshot.SourceHash != "" {
			result.SourceHash = staleSnapshot.SourceHash
			fetched := staleSnapshot.FetchedAt
			result.SourceFetchedAt = &fetched
			evidence["stale_cache_present"] = true
			evidence["stale_cache_used_for_match"] = false
		}
		return result
	}
	result := evaluatePlannedOutageSnapshot(snapshot, location, occurredAt, fromCache)
	if result.Decision == "AMBIGUOUS" && fromCache {
		refreshed, _, _, refreshErr := g.snapshot(ctx, location, occurredAt, true)
		if refreshErr == nil {
			result = evaluatePlannedOutageSnapshot(refreshed, location, occurredAt, false)
			result.Evidence["forced_refresh_after_ambiguous"] = true
		}
	}
	return result
}

func (g *plannedOutageGate) snapshot(ctx context.Context, location chatbotLocationInput, occurredAt time.Time, force bool) (plannedOutageSnapshot, bool, plannedOutageSnapshot, error) {
	g.mu.Lock()
	cached := g.cache.snapshot
	g.mu.Unlock()
	if !force && cached.SourceHash != "" {
		ttl := g.cacheTTL(cached, location, occurredAt)
		if time.Since(cached.FetchedAt) <= ttl {
			return cached, true, plannedOutageSnapshot{}, nil
		}
	}
	g.fetchMu.Lock()
	defer g.fetchMu.Unlock()
	g.mu.Lock()
	cached = g.cache.snapshot
	g.mu.Unlock()
	if !force && cached.SourceHash != "" {
		ttl := g.cacheTTL(cached, location, occurredAt)
		if time.Since(cached.FetchedAt) <= ttl {
			return cached, true, plannedOutageSnapshot{}, nil
		}
	}
	fresh, err := g.fetchWithRetry(ctx)
	if err != nil {
		_ = g.tryPublicPageFallback(ctx)
		return plannedOutageSnapshot{}, false, cached, err
	}
	g.mu.Lock()
	g.cache.snapshot = fresh
	g.mu.Unlock()
	return fresh, false, plannedOutageSnapshot{}, nil
}

func (g *plannedOutageGate) cacheTTL(snapshot plannedOutageSnapshot, location chatbotLocationInput, occurredAt time.Time) time.Duration {
	province := normalizePlannedText(location.Province)
	key := plannedLocationKey(location.HouseOrVillage)
	for _, record := range snapshot.Records {
		if normalizePlannedText(record.Province) != province || !plannedAreaContainsLocation(record.Area, key) {
			continue
		}
		start, startOK := parsePlannedOutageTime(record.StartDate)
		end, endOK := parsePlannedOutageTime(record.EndDate)
		if !startOK || !endOK {
			continue
		}
		if absDuration(occurredAt.Sub(start)) <= 30*time.Minute || absDuration(occurredAt.Sub(end)) <= 30*time.Minute {
			return g.hotTTL
		}
	}
	return g.normalTTL
}

func (g *plannedOutageGate) fetchWithRetry(ctx context.Context) (plannedOutageSnapshot, error) {
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 {
			backoff := time.Duration(150*(1<<(attempt-1))) * time.Millisecond
			select {
			case <-ctx.Done():
				return plannedOutageSnapshot{}, ctx.Err()
			case <-time.After(backoff):
			}
		}
		snapshot, err := g.fetchAllOutages(ctx)
		if err == nil {
			return snapshot, nil
		}
		lastErr = err
	}
	if lastErr == nil {
		lastErr = errors.New("planned outage source unavailable")
	}
	return plannedOutageSnapshot{}, lastErr
}

func (g *plannedOutageGate) fetchAllOutages(ctx context.Context) (plannedOutageSnapshot, error) {
	const pageSize = 500
	all := make([]plannedOutageSourceRecord, 0, pageSize)
	start := 0
	for {
		form := url.Values{}
		form.Set("draw", "1")
		form.Set("start", strconv.Itoa(start))
		form.Set("length", strconv.Itoa(pageSize))
		form.Set("province", "")
		form.Set("date", "")
		form.Set("detail", "")
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, g.baseURL+"/Home/GetOutages", strings.NewReader(form.Encode()))
		if err != nil {
			return plannedOutageSnapshot{}, err
		}
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
		req.Header.Set("Accept", "application/json")
		resp, err := g.httpClient.Do(req)
		if err != nil {
			return plannedOutageSnapshot{}, err
		}
		body, readErr := io.ReadAll(io.LimitReader(resp.Body, 5_000_000))
		_ = resp.Body.Close()
		if readErr != nil {
			return plannedOutageSnapshot{}, readErr
		}
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return plannedOutageSnapshot{}, fmt.Errorf("eservice list status %d", resp.StatusCode)
		}
		var page plannedOutageListResponse
		if err := json.Unmarshal(body, &page); err != nil {
			return plannedOutageSnapshot{}, fmt.Errorf("eservice list schema: %w", err)
		}
		all = append(all, page.Data...)
		start += len(page.Data)
		if len(page.Data) == 0 || start >= page.RecordsFiltered || start >= page.RecordsTotal {
			break
		}
		if start > 10_000 {
			return plannedOutageSnapshot{}, errors.New("eservice list exceeds safety page limit")
		}
	}
	sort.Slice(all, func(i, j int) bool { return all[i].OutageID < all[j].OutageID })
	canonical, err := json.Marshal(all)
	if err != nil {
		return plannedOutageSnapshot{}, err
	}
	sum := sha256.Sum256(canonical)
	return plannedOutageSnapshot{
		Records:    all,
		FetchedAt:  time.Now().UTC(),
		SourceHash: hex.EncodeToString(sum[:]),
		SourceMode: plannedOutageSourcePrimary,
	}, nil
}

func (g *plannedOutageGate) tryPublicPageFallback(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, g.baseURL+"/", nil)
	if err != nil {
		return err
	}
	resp, err := g.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 256_000))
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("public page fallback status %d", resp.StatusCode)
	}
	if !bytes.Contains(body, []byte("/PowerOutage/Home/GetOutages")) {
		return errors.New("public page fallback schema not recognized")
	}
	return errors.New("public page is client-rendered and contains no authoritative server-rendered outage rows")
}

func evaluatePlannedOutageSnapshot(snapshot plannedOutageSnapshot, location chatbotLocationInput, occurredAt time.Time, fromCache bool) plannedOutageCheck {
	province := normalizePlannedText(location.Province)
	locationKey := plannedLocationKey(location.HouseOrVillage)
	active := []plannedOutageNotice{}
	ambiguous := []plannedOutageNotice{}
	upcoming := []plannedOutageNotice{}
	ended := []plannedOutageNotice{}
	for _, record := range snapshot.Records {
		if normalizePlannedText(record.Province) != province {
			continue
		}
		if !plannedAreaContainsLocation(record.Area, locationKey) {
			continue
		}
		start, startOK := parsePlannedOutageTime(record.StartDate)
		end, endOK := parsePlannedOutageTime(record.EndDate)
		if !startOK || !endOK || end.Before(start) {
			continue
		}
		notice := plannedNotice(record, start, end, occurredAt)
		notice.AdminMatch = plannedAdminScopeMatches(record.Area, location)
		if notice.AdminMatch {
			notice.EvidenceLevel = "ADMIN_LOCATION_DETERMINISTIC"
		} else {
			notice.EvidenceLevel = "TEXT_LOCATION_CANDIDATE_NEEDS_ADMIN"
		}
		switch {
		case occurredAt.Before(start):
			upcoming = append(upcoming, notice)
		case occurredAt.After(end):
			ended = append(ended, notice)
		case notice.PartialArea || !notice.AdminMatch:
			ambiguous = append(ambiguous, notice)
		default:
			active = append(active, notice)
		}
	}
	decision := "NO_MATCH"
	basis := "no_active_deterministic_notice_match"
	candidates := []plannedOutageNotice{}
	if len(active) == 1 && len(ambiguous) == 0 {
		decision = "MATCHED"
		basis = "single_active_deterministic_admin_location_and_time_match"
		candidates = active
	} else if len(active)+len(ambiguous) > 1 || len(ambiguous) > 0 {
		decision = "AMBIGUOUS"
		basis = "missing_admin_scope_partial_area_or_multiple_active_candidates"
		candidates = append(candidates, active...)
		candidates = append(candidates, ambiguous...)
	}
	relevant := make([]plannedOutageNotice, 0, len(active)+len(ambiguous)+len(upcoming)+len(ended))
	relevant = append(relevant, active...)
	relevant = append(relevant, ambiguous...)
	relevant = append(relevant, upcoming...)
	relevant = append(relevant, ended...)
	relevantHash := plannedNoticeSetHash(relevant)
	evidence := map[string]any{
		"source":                         "pea_eservice_power_outage",
		"source_mode":                    snapshot.SourceMode,
		"source_hash":                    snapshot.SourceHash,
		"source_fetched_at":              snapshot.FetchedAt.Format(time.RFC3339),
		"relevant_evidence_hash":         relevantHash,
		"cache_used":                     fromCache,
		"decision_basis":                 basis,
		"deterministic_only":             true,
		"ai_parser_used":                 false,
		"ai_decision_allowed":            false,
		"planned_end_is_restoration_eta": false,
		"active_candidate_ids":           noticeIDs(active),
		"ambiguous_candidate_ids":        noticeIDs(ambiguous),
		"upcoming_candidate_ids":         noticeIDs(upcoming),
		"ended_candidate_ids":            noticeIDs(ended),
	}
	result := plannedOutageCheck{
		Decision:     decision,
		SourceMode:   snapshot.SourceMode,
		SourceHash:   snapshot.SourceHash,
		Evidence:     evidence,
		RelevantHash: relevantHash,
	}
	fetched := snapshot.FetchedAt
	result.SourceFetchedAt = &fetched
	if len(candidates) > 0 {
		raw, _ := json.Marshal(candidates)
		result.RawSnapshot = raw
		expires := time.Now().UTC().Add(90 * 24 * time.Hour)
		result.RawExpiresAt = &expires
	}
	if decision == "MATCHED" {
		result.NoticeID = active[0].ID
		result.NoticeRevisionHash = active[0].RevisionHash
		evidence["matched_notice"] = active[0]
	}
	return result
}

func plannedNotice(record plannedOutageSourceRecord, start, end, occurredAt time.Time) plannedOutageNotice {
	revisionBasis, _ := json.Marshal(map[string]any{
		"id":       record.OutageID,
		"province": record.Province,
		"area":     strings.TrimSpace(record.Area),
		"detail":   strings.TrimSpace(record.Detail),
		"start":    start.UTC().Format(time.RFC3339),
		"end":      end.UTC().Format(time.RFC3339),
	})
	sum := sha256.Sum256(revisionBasis)
	relation := "ACTIVE"
	if occurredAt.Before(start) {
		relation = "UPCOMING"
	}
	if occurredAt.After(end) {
		relation = "ENDED"
	}
	return plannedOutageNotice{
		ID:            record.OutageID,
		Province:      strings.TrimSpace(record.Province),
		Area:          strings.TrimSpace(record.Area),
		Detail:        strings.TrimSpace(record.Detail),
		ReasonCode:    plannedReasonCode(record.Detail),
		Start:         start.UTC(),
		End:           end.UTC(),
		OfficeID:      strings.TrimSpace(record.OfficeID),
		PEAOffice:     strings.TrimSpace(record.PEAOffice),
		RevisionHash:  hex.EncodeToString(sum[:]),
		SourceRef:     "/PowerOutage/Home/Detail/" + record.OutageID,
		PartialArea:   plannedAreaLooksPartial(record.Area),
		LocationMatch: true,
		TimeRelation:  relation,
	}
}

func plannedLocationKey(value string) string {
	value = plannedOutageMooPattern.ReplaceAllString(value, " ")
	value = strings.TrimSpace(value)
	value = strings.TrimPrefix(value, "หมู่บ้าน")
	return normalizePlannedText(value)
}

func plannedAreaContainsLocation(area, locationKey string) bool {
	if locationKey == "" || len([]rune(locationKey)) < 4 {
		return false
	}
	areaKey := normalizePlannedText(area)
	if strings.Contains(areaKey, locationKey) {
		return true
	}
	withoutBan := strings.TrimPrefix(locationKey, "บ้าน")
	return len([]rune(withoutBan)) >= 4 && strings.Contains(areaKey, withoutBan)
}

func plannedAdminScopeMatches(area string, location chatbotLocationInput) bool {
	district := normalizeChatbotAdmin(location.District, "อำเภอ", "อ.")
	subdistrict := normalizeChatbotAdmin(location.Subdistrict, "ตำบล", "ต.")
	if district == "" || subdistrict == "" {
		return false
	}
	if !plannedAreaHasLabeledAdmin(area, []string{subdistrict}, []string{"ตำบล", "ต."}) {
		return false
	}
	districtAliases := []string{district}
	if strings.HasPrefix(district, "เมือง") {
		trimmed := strings.TrimPrefix(district, "เมือง")
		if trimmed != "" {
			districtAliases = append(districtAliases, trimmed)
		}
	} else {
		districtAliases = append(districtAliases, "เมือง"+district)
	}
	return plannedAreaHasLabeledAdmin(area, districtAliases, []string{"อำเภอ", "อ."})
}

func plannedAreaHasLabeledAdmin(area string, values, labels []string) bool {
	areaKey := normalizePlannedText(area)
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		for _, label := range labels {
			needle := normalizePlannedText(label + value)
			if needle != "" && strings.Contains(areaKey, needle) {
				return true
			}
		}
	}
	return false
}

func plannedAreaLooksPartial(area string) bool {
	value := normalizePlannedText(area)
	for _, marker := range []string{"บางส่วน", "ช่วง", "ตั้งแต่", "ถึง", "ฝั่ง", "บริเวณ", "จาก"} {
		if strings.Contains(value, marker) {
			return true
		}
	}
	return false
}

func normalizePlannedText(value string) string {
	value = strings.ToLower(strings.TrimSpace(value))
	var b strings.Builder
	for _, r := range value {
		if unicode.IsSpace(r) || strings.ContainsRune(".,;:()[]{}-_–—/\\'\"", r) {
			continue
		}
		b.WriteRune(r)
	}
	return b.String()
}

func plannedNoticeSetHash(values []plannedOutageNotice) string {
	parts := make([]string, 0, len(values))
	for _, value := range values {
		parts = append(parts, strings.Join([]string{
			value.ID,
			value.RevisionHash,
			value.TimeRelation,
			value.EvidenceLevel,
			strconv.FormatBool(value.PartialArea),
			strconv.FormatBool(value.AdminMatch),
		}, "|"))
	}
	sort.Strings(parts)
	raw, _ := json.Marshal(parts)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}
func parsePlannedOutageTime(value string) (time.Time, bool) {
	match := plannedOutageDatePattern.FindStringSubmatch(strings.TrimSpace(value))
	if len(match) != 2 {
		return time.Time{}, false
	}
	ms, err := strconv.ParseInt(match[1], 10, 64)
	if err != nil {
		return time.Time{}, false
	}
	return time.UnixMilli(ms).UTC(), true
}

func plannedReasonCode(detail string) string {
	value := normalizePlannedText(detail)
	switch {
	case strings.Contains(value, "ตัดต้นไม้") || strings.Contains(value, "ตัดกิ่ง") || strings.Contains(value, "ริดรอนต้นไม้"):
		return "TREE_TRIMMING"
	case strings.Contains(value, "ย้ายเสา") || strings.Contains(value, "ย้ายแนวเสา"):
		return "POLE_RELOCATION"
	case strings.Contains(value, "ปรับปรุง") || strings.Contains(value, "บำรุง") || strings.Contains(value, "ซ่อม") || strings.Contains(value, "เปลี่ยนอุปกรณ์") || strings.Contains(value, "พาดสาย"):
		return "MAINTENANCE"
	default:
		return "OTHER"
	}
}

func noticeIDs(values []plannedOutageNotice) []string {
	ids := make([]string, 0, len(values))
	for _, value := range values {
		ids = append(ids, value.ID)
	}
	sort.Strings(ids)
	return ids
}

func plannedOutageDecisionHash(ticketID string, result plannedOutageCheck) string {
	basis, _ := json.Marshal(map[string]any{
		"ticket_id":              ticketID,
		"decision":               result.Decision,
		"relevant_evidence_hash": result.RelevantHash,
		"source_mode":            result.SourceMode,
		"notice_id":              result.NoticeID,
		"notice_revision_hash":   result.NoticeRevisionHash,
		"source_stale":           result.SourceStale,
	})
	sum := sha256.Sum256(basis)
	return hex.EncodeToString(sum[:])
}
func plannedOutageErrorClass(err error) string {
	if err == nil {
		return ""
	}
	text := strings.ToLower(err.Error())
	switch {
	case errors.Is(err, context.DeadlineExceeded) || strings.Contains(text, "timeout"):
		return "TIMEOUT"
	case strings.Contains(text, "status 401") || strings.Contains(text, "status 403"):
		return "ACCESS_BLOCKED"
	case strings.Contains(text, "schema"):
		return "SCHEMA_CHANGED"
	default:
		return "SOURCE_ERROR"
	}
}

func absDuration(value time.Duration) time.Duration {
	if value < 0 {
		return -value
	}
	return value
}
