param(
  [string]$BaseUrl = "https://pea-api-intellisense-api.onrender.com",
  [string]$WebUrl = "https://pea-api-intellisense-web.onrender.com",
  [string]$ApiKey = $env:AIS_INBOUND_API_KEY,
  [int]$Limit = 200,
  [string]$OutputDir = "runtime/private/production_gate"
)

$ErrorActionPreference = "Stop"

if (-not $ApiKey) {
  throw "AIS_INBOUND_API_KEY is required in environment or -ApiKey. Do not paste it into chat."
}

$cleanBase = $BaseUrl.TrimEnd("/")
$cleanWeb = $WebUrl.TrimEnd("/")
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

$operator = Invoke-RestMethod -Method GET -Uri "$cleanBase/api/v1/ais/outage-verifications?view=operator&limit=$Limit" -Headers $headers -TimeoutSec 30
Assert-Blocked $operator "operator"

$truthIntervalStatus = "UNAVAILABLE"
$truthIntervals = @()
try {
  $truthIntervalResponse = Invoke-RestMethod -Method GET -Uri "$cleanBase/api/v1/ais/truth-intervals?status=OPEN&limit=50" -Headers $headers -TimeoutSec 25
  Assert-Blocked $truthIntervalResponse "truth_intervals"
  $truthIntervals = @($truthIntervalResponse.items)
  $truthIntervalStatus = "PASS"
} catch {
  $truthIntervalStatus = "NOT_DEPLOYED_OR_UNAVAILABLE"
}

$items = @($operator.items)
$realItems = @($items)

$latestReal = $realItems | Select-Object -First 1
$latestAny = $items | Select-Object -First 1
$latest = if ($latestReal) { $latestReal } else { $latestAny }

$truthEventCounts = Count-Values (@($realItems | ForEach-Object { $_.truth_observation.event_type }))
$truthValidationCounts = Count-Values (@($realItems | ForEach-Object { $_.truth_observation.validation_status }))
$callbackCounts = Count-Values (@($realItems | ForEach-Object { $_.callback_status }))
$outboxCounts = Count-Values (@($realItems | ForEach-Object { $_.callback_outbox.status }))

$modelReadyRows = [int64]$metrics.model_ready_clean_truth_rows

$webStatus = "SKIPPED"
$webHasDemoLabel = $false
if ($cleanWeb) {
  try {
    $webHtml = curl.exe -sS --max-time 25 "$cleanWeb/"
    $webHasDemoLabel = $webHtml -match "DEMO DATA"
    $webStatus = if ($webHasDemoLabel) { "PASS" } else { "WARN" }
  } catch {
    $webStatus = "WARN"
  }
}

$checks = @()
$checks += New-Check "cloud_health" $(if ($health.status -eq "ok" -and $health.database -eq "ok") { "PASS" } else { "FAIL" }) "health=$($health.status), database=$($health.database)" "health/database must be ok"
$checks += New-Check "production_send_block" $(if ($health.production_send -eq "blocked" -and $metrics.production_send -eq "blocked" -and $operator.production_send -eq "blocked") { "PASS" } else { "FAIL" }) "health=$($health.production_send), metrics=$($metrics.production_send), operator=$($operator.production_send)" "all public/operator surfaces must stay blocked"
$checks += New-Check "real_ais_seen" $(if ($realItems.Count -gt 0) { "PASS" } else { "WARN" }) "non_smoke_requests_in_window=$($realItems.Count)" "real AIS should be visible in latest operator window"
$checks += New-Check "truth_review_queue" $(if ([int64]$metrics.truth_review_needed -eq 0) { "PASS" } else { "FAIL" }) "truth_review_needed=$($metrics.truth_review_needed)" "truth_review_needed must be 0 before customer send"
$checks += New-Check "truth_interval_state" $(if ([int64]$metrics.truth_open_intervals -eq 0) { "PASS" } else { "WARN" }) "open=$($metrics.truth_open_intervals), closed=$($metrics.truth_closed_intervals)" "open intervals must be explained as active outage or missing restore"
$checks += New-Check "truth_interval_detail" $(if ([int64]$metrics.truth_open_intervals -eq 0 -or $truthIntervalStatus -eq "PASS") { "PASS" } else { "WARN" }) "detail_status=$truthIntervalStatus, open_detail_rows=$($truthIntervals.Count)" "open interval detail endpoint should be available for owner review"
$checks += New-Check "callback_contract" $(if ($callbackCounts.Contains("CAPTURED_NO_CALLBACK_URL")) { "BLOCKED" } else { "WARN" }) "callback_counts=$(($callbackCounts | ConvertTo-Json -Compress))" "AIS callback URL/contract must be approved before real callback"
$checks += New-Check "clean_truth_capture" $(if ($modelReadyRows -ge 30) { "WARN" } else { "BLOCKED" }) "model_ready_rows=$modelReadyRows, independent_incident_target=30" "model-ready rows still require local incident grouping and MAE/coverage evaluation"
$checks += New-Check "web_console" $webStatus "demo_label=$webHasDemoLabel" "public web console must show synthetic demo data only"

$overall = "PASS_FOR_SHADOW_CAPTURE_ONLY"
if (@($checks | Where-Object { $_.status -eq "FAIL" }).Count -gt 0) {
  $overall = "FAIL_FIX_BEFORE_NEXT_STEP"
} elseif (@($checks | Where-Object { $_.status -eq "BLOCKED" }).Count -gt 0) {
  $overall = "BLOCKED_BEFORE_CUSTOMER_SEND"
} elseif (@($checks | Where-Object { $_.status -eq "WARN" }).Count -gt 0) {
  $overall = "WARN_REVIEW_BEFORE_PILOT"
}

$latestSummary = $null
if ($latest) {
  $latestSummary = [ordered]@{
    request_ref = $latest.request_ref
    received_at = $latest.received_at
    status = $latest.status
    callback_status = $latest.callback_status
    production_send = $latest.production_send
    truth_event_type = $latest.truth_observation.event_type
    truth_validation = $latest.truth_observation.validation_status
    outbox_status = $latest.callback_outbox.status
    outbox_transport = $latest.callback_outbox.transport
  }
}

$report = [ordered]@{
  generated_at = $generatedAt.ToString("yyyy-MM-ddTHH:mm:ssZ")
  run_id = $runId
  base_url = $cleanBase
  web_url = $cleanWeb
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
    truth_review_needed = $metrics.truth_review_needed
    truth_outage_events = $metrics.truth_outage_events
    truth_restore_events = $metrics.truth_restore_events
    truth_open_intervals = $metrics.truth_open_intervals
    truth_closed_intervals = $metrics.truth_closed_intervals
  }
  operator_window = [ordered]@{
    limit = $Limit
    items_returned = $items.Count
    non_smoke_items = $realItems.Count
    truth_event_counts = $truthEventCounts
    truth_validation_counts = $truthValidationCounts
    callback_counts = $callbackCounts
    outbox_counts = $outboxCounts
    latest = $latestSummary
  }
  truth_interval_review = [ordered]@{
    detail_status = $truthIntervalStatus
    open_detail_rows = $truthIntervals.Count
    note = "Rows are available only after the redacted truth-interval endpoint is deployed."
  }
  checks = $checks
  safety = [ordered]@{
    redaction = "Report omits API keys, full meter numbers, PEANO lists, customer identity, room ids, tokens, and raw WebEx/Line text."
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

$latestLines = if ($latestSummary) {
  @(
    "- request_ref: $($latestSummary.request_ref)",
    "- received_at: $($latestSummary.received_at)",
    "- callback_status: $($latestSummary.callback_status)",
    "- truth_event_type: $($latestSummary.truth_event_type)",
    "- truth_validation: $($latestSummary.truth_validation)",
    "- outbox: $($latestSummary.outbox_transport) / $($latestSummary.outbox_status)",
    "- production_send: $($latestSummary.production_send)"
  )
} else {
  @("- none")
}

$markdown = @(
  "# Production Gate Live Snapshot",
  "",
  "- Generated: $($report.generated_at)",
  "- Overall status: $($report.overall_status)",
  "- Mode: $($report.mode)",
  "- Production send: $($report.production_send)",
  "- API: $($report.base_url)",
  "- Web: $($report.web_url)",
  "",
  "## Metrics",
  "",
  "- total_requests: $($metrics.total_requests)",
  "- non_smoke_requests_in_window: $($realItems.Count)",
  "- truth_observations: $($metrics.truth_observations)",
  "- truth_review_needed: $($metrics.truth_review_needed)",
  "- truth_outage_events: $($metrics.truth_outage_events)",
  "- truth_restore_events: $($metrics.truth_restore_events)",
  "- truth_open_intervals: $($metrics.truth_open_intervals)",
  "- truth_closed_intervals: $($metrics.truth_closed_intervals)",
  "- truth_interval_detail_status: $truthIntervalStatus",
  "- truth_interval_detail_rows: $($truthIntervals.Count)",
  "- outbox_dry_run_held: $($metrics.outbox_dry_run_held)",
  "",
  "## Latest Redacted Request",
  ""
) + $latestLines + @(
  "",
  "## Gate Checks",
  "",
  "| Check | Status | Evidence |",
  "|---|---|---|"
) + $checkLines + @(
  "",
  "## Decision",
  "",
  "Shadow capture can continue. Customer-facing callback/ETR remains blocked until callback contract, topology owner approval, and green gate pass.",
  "",
  "## Safety",
  "",
  "This report omits API keys, full meter numbers, PEANO lists, customer identity, room ids, tokens, and raw WebEx/Line text."
)

$markdown | Set-Content -LiteralPath $mdPath -Encoding UTF8

$report | ConvertTo-Json -Depth 12
