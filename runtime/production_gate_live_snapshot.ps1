param(
  [string]$BaseUrl = "https://pea-api-intellisense-api.onrender.com",
  [string]$ApiKey = $env:AIS_INBOUND_API_KEY,
  [int]$Limit = 200,
  [string]$OutputDir = "runtime/private/production_gate"
)

$ErrorActionPreference = "Stop"

if (-not $ApiKey) {
  throw "AIS_INBOUND_API_KEY is required in environment or -ApiKey. Do not paste it into chat."
}

$cleanBase = $BaseUrl.TrimEnd("/")
$headers = @{ "X-API-Key" = $ApiKey }
$generatedAt = (Get-Date).ToUniversalTime()
$runId = $generatedAt.ToString("yyyyMMddTHHmmssZ")

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

function Assert-Blocked {
  param($Payload, [string]$Label)
  if ($Payload.production_send -ne "blocked") {
    throw "Unsafe $Label response: production_send=$($Payload.production_send)"
  }
}

function Count-Values {
  param($Values)
  $map = [ordered]@{}
  foreach ($value in @($Values)) {
    $key = [string]$value
    if (-not $key) { $key = "(blank)" }
    if (-not $map.Contains($key)) { $map[$key] = 0 }
    $map[$key]++
  }
  return $map
}

function Metric-Int {
  param($Payload, [string]$Name)
  $property = $Payload.PSObject.Properties[$Name]
  if ($null -eq $property -or $null -eq $property.Value) { return [int64]0 }
  return [int64]$property.Value
}

function New-Check {
  param(
    [string]$Name,
    [string]$Status,
    [string]$Evidence,
    [string]$Required
  )
  return [ordered]@{
    name = $Name
    status = $Status
    evidence = $Evidence
    required = $Required
  }
}

$health = Invoke-RestMethod -Method GET -Uri "$cleanBase/health" -TimeoutSec 20
Assert-Blocked $health "health"

$metrics = Invoke-RestMethod -Method GET -Uri "$cleanBase/metrics" -Headers $headers -TimeoutSec 25
Assert-Blocked $metrics "metrics"

$truthIntervalStatus = "UNAVAILABLE"
try {
  $truthIntervalResponse = Invoke-RestMethod -Method GET -Uri "$cleanBase/api/v1/ais/truth-intervals?status=ALL&limit=$Limit" -Headers $headers -TimeoutSec 25
  Assert-Blocked $truthIntervalResponse "truth_intervals"
  $truthIntervalStatus = "PASS"
} catch {
  $truthIntervalStatus = "NOT_DEPLOYED_OR_UNAVAILABLE"
}

$modelReadyRows = Metric-Int $metrics "model_ready_clean_truth_rows"
$v2ModelReadyRows = Metric-Int $metrics "v2_model_ready_rows"
$v2OutageEvents = Metric-Int $metrics "v2_outage_events"
$v2RestoreEvents = Metric-Int $metrics "v2_restore_events"
$v2OpenIntervals = Metric-Int $metrics "v2_open_intervals"
$v2DurationReview = Metric-Int $metrics "v2_duration_review"
$truthReviewNeeded = Metric-Int $metrics "truth_review_needed"
$truthOpenIntervals = Metric-Int $metrics "truth_open_intervals"
$truthClosedIntervals = Metric-Int $metrics "truth_closed_intervals"
$callbackCounts = $metrics.callback_counts
if ($null -eq $callbackCounts) { $callbackCounts = @{} }
$mappingVersion = [string]$metrics.semantic_mapping_version
$meterStateAligned = $mappingVersion -eq "alarm_mapping_v2" -and $modelReadyRows -eq $v2ModelReadyRows

$checks = @()
$checks += New-Check "cloud_health" $(if ($health.status -eq "ok" -and $health.database -eq "ok") { "PASS" } else { "FAIL" }) "health=$($health.status), database=$($health.database)" "health/database must be ok"
$checks += New-Check "production_send_block" $(if ($health.production_send -eq "blocked" -and $metrics.production_send -eq "blocked") { "PASS" } else { "FAIL" }) "health=$($health.production_send), metrics=$($metrics.production_send)" "all customer-send surfaces must remain blocked"
$checks += New-Check "meter_state_truth_alignment" $(if ($meterStateAligned) { "PASS" } else { "FAIL" }) "mapping_version=$mappingVersion, model_ready=$modelReadyRows, v2_model_ready=$v2ModelReadyRows" "only alarm_mapping_v2 meter-state pairs may count as model-ready truth"
$checks += New-Check "truth_review_queue" $(if ($truthReviewNeeded -eq 0) { "PASS" } else { "WARN" }) "truth_review_needed=$truthReviewNeeded" "review rows are operationally pending and cannot support customer send"
$checks += New-Check "truth_interval_state" $(if ($truthOpenIntervals -eq 0) { "PASS" } else { "WARN" }) "open=$truthOpenIntervals, v2_open=$v2OpenIntervals, closed=$truthClosedIntervals" "open intervals require active-outage or missing-restore review"
$checks += New-Check "truth_interval_detail" $(if ($truthOpenIntervals -eq 0 -or $truthIntervalStatus -eq "PASS") { "PASS" } else { "WARN" }) "detail_status=$truthIntervalStatus" "redacted truth-interval endpoint must remain available for review"
$checks += New-Check "callback_contract" "BLOCKED" "callback_counts=$(($callbackCounts | ConvertTo-Json -Compress))" "no real callback until a separately approved contract and production gate"
$checks += New-Check "model_evaluation_readiness" $(if ($v2ModelReadyRows -ge 30) { "WARN" } else { "BLOCKED" }) "v2_model_ready_rows=$v2ModelReadyRows, independent_incident_target=30" "row count is not an accuracy claim; local chronological incident grouping and evaluation are still required"
$checks += New-Check "duration_review" $(if ($v2DurationReview -eq 0) { "PASS" } else { "WARN" }) "v2_duration_review=$v2DurationReview" "duration-review rows remain outside training and evaluation"

$overall = "PASS_FOR_SHADOW_CAPTURE_ONLY"
if (@($checks | Where-Object { $_.status -eq "FAIL" }).Count -gt 0) {
  $overall = "FAIL_FIX_BEFORE_NEXT_STEP"
} elseif (@($checks | Where-Object { $_.status -eq "BLOCKED" }).Count -gt 0) {
  $overall = "BLOCKED_BEFORE_CUSTOMER_SEND"
} elseif (@($checks | Where-Object { $_.status -eq "WARN" }).Count -gt 0) {
  $overall = "WARN_REVIEW_BEFORE_PILOT"
}

$report = [ordered]@{
  generated_at = $generatedAt.ToString("yyyy-MM-ddTHH:mm:ssZ")
  run_id = $runId
  base_url = $cleanBase
  overall_status = $overall
  mode = $health.mode
  production_send = $health.production_send
  metrics = [ordered]@{
    total_requests = $metrics.total_requests
    duplicate_callbacks = $metrics.duplicate_callbacks
    pending_worker_traces = $metrics.pending_worker_traces
    not_ready_etr = $metrics.not_ready_etr
    outbox_dry_run_held = $metrics.outbox_dry_run_held
    dead_letters = $metrics.dead_letters
    truth_observations = $metrics.truth_observations
    truth_outage_events = $metrics.truth_outage_events
    truth_restore_events = $metrics.truth_restore_events
    truth_open_intervals = $truthOpenIntervals
    truth_closed_intervals = $truthClosedIntervals
    truth_review_needed = $truthReviewNeeded
    semantic_mapping_version = $mappingVersion
    v2_outage_events = $v2OutageEvents
    v2_restore_events = $v2RestoreEvents
    v2_open_intervals = $v2OpenIntervals
    v2_model_ready_rows = $v2ModelReadyRows
    v2_duration_review = $v2DurationReview
    model_ready_clean_truth_rows = $modelReadyRows
  }
  truth_interval_review = [ordered]@{
    detail_status = $truthIntervalStatus
    note = "Only aggregate endpoint availability is recorded here; row-level review is written by open_interval_review.ps1 with hashed references."
  }
  checks = $checks
  safety = [ordered]@{
    redaction = "Report contains aggregates only. It omits API keys, request/source-event identifiers, full meter numbers, PEANO lists, customer identity, room ids, tokens, and raw WebEx/Line text."
    production_send = "blocked"
    line_webex_policy = "Line/WebEx may be collected only as bounded context, not outage/restore truth."
  }
}

$jsonPath = Join-Path $OutputDir "production_gate_live_snapshot_$runId.json"
$mdPath = Join-Path $OutputDir "production_gate_live_snapshot_$runId.md"

$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$checkLines = @()
foreach ($check in $checks) {
  $checkLines += "| $($check.name) | $($check.status) | $($check.evidence) |"
}

$markdown = @(
  "# Production Gate Live Snapshot",
  "",
  "- Generated: $($report.generated_at)",
  "- Overall status: $($report.overall_status)",
  "- Mode: $($report.mode)",
  "- Production send: $($report.production_send)",
  "- API: $($report.base_url)",
  "",
  "## Metrics",
  "",
  "- total_requests: $($metrics.total_requests)",
  "- truth_observations: $($metrics.truth_observations)",
  "- truth_review_needed: $truthReviewNeeded",
  "- truth_outage_events: $($metrics.truth_outage_events)",
  "- truth_restore_events: $($metrics.truth_restore_events)",
  "- truth_open_intervals: $truthOpenIntervals",
  "- truth_closed_intervals: $truthClosedIntervals",
  "- semantic_mapping_version: $mappingVersion",
  "- v2_outage_events: $v2OutageEvents",
  "- v2_restore_events: $v2RestoreEvents",
  "- v2_open_intervals: $v2OpenIntervals",
  "- v2_model_ready_rows: $v2ModelReadyRows",
  "- model_ready_clean_truth_rows: $modelReadyRows",
  "- v2_duration_review: $v2DurationReview",
  "- truth_interval_detail_status: $truthIntervalStatus",
  "- outbox_dry_run_held: $($metrics.outbox_dry_run_held)",
  ""
) + @(
  "",
  "## Gate Checks",
  "",
  "| Check | Status | Evidence |",
  "|---|---|---|"
) + $checkLines + @(
  "",
  "## Decision",
  "",
  "Shadow capture can continue. Model-ready meter-state rows must first be grouped into independent incidents and evaluated chronologically. Customer-facing callback/ETR remains blocked until the model, contract, and owner gates pass.",
  "",
  "## Safety",
  "",
  "This aggregate report omits API keys, request/source-event identifiers, full meter numbers, PEANO lists, customer identity, room ids, tokens, and raw WebEx/Line text."
)

$markdown | Set-Content -LiteralPath $mdPath -Encoding UTF8

$report | ConvertTo-Json -Depth 12
