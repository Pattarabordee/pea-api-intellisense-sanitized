param(
  [string]$BaseUrl = "https://pea-api-intellisense-api.onrender.com",
  [string]$ApiKey = $env:AIS_INBOUND_API_KEY,
  [int]$Limit = 50,
  [string]$OutputDir = "runtime/private/open_interval_review"
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

function Safe-Text {
  param($Value)
  if ($null -eq $Value) { return "" }
  return [string]$Value
}

function Interval-Action {
  param($Item)
  if ((Safe-Text $Item.pair_status) -eq "CLOSED") { return "no_action_paired" }
  if ((Safe-Text $Item.pair_status) -eq "REVIEW") { return "manual_review_required" }
  return "confirm_active_outage_or_missing_restore_with_owner"
}

$metrics = Invoke-RestMethod -Method GET -Uri "$cleanBase/metrics" -Headers $headers -TimeoutSec 25
Assert-Blocked $metrics "metrics"

$detailStatus = "UNAVAILABLE"
$items = @()
$detailError = ""
try {
  $detail = Invoke-RestMethod -Method GET -Uri "$cleanBase/api/v1/ais/truth-intervals?status=OPEN&limit=$Limit" -Headers $headers -TimeoutSec 25
  Assert-Blocked $detail "truth_intervals"
  $items = @($detail.items)
  $detailStatus = "PASS"
} catch {
  $detailStatus = "NOT_DEPLOYED_OR_UNAVAILABLE"
  $detailError = $_.Exception.Message
}

$reviewRows = @()
foreach ($item in $items) {
  $ageHours = $null
  if ($item.outage_at) {
    try {
      $outageAt = [DateTimeOffset]::Parse([string]$item.outage_at).ToUniversalTime()
      $ageHours = [Math]::Round(($generatedAt - $outageAt.UtcDateTime).TotalHours, 2)
    } catch {
      $ageHours = $null
    }
  }
  $reviewRows += [ordered]@{
    interval_id = Safe-Text $item.interval_id
    pair_status = Safe-Text $item.pair_status
    outage_request_id = Safe-Text $item.outage_request_id
    restore_request_id = Safe-Text $item.restore_request_id
    outage_at = Safe-Text $item.outage_at
    restore_at = Safe-Text $item.restore_at
    age_hours = $ageHours
    duration_minutes = $item.duration_minutes
    meter_last4 = Safe-Text $item.meter.last4
    site_last4 = Safe-Text $item.site.last4
    review_hint = Safe-Text $item.review_hint
    evidence_reason = Safe-Text $item.evidence.reason
    recommended_action = Interval-Action $item
  }
}

$overall = if ([int64]$metrics.truth_open_intervals -eq 0) {
  "PASS_NO_OPEN_INTERVALS"
} elseif ($detailStatus -eq "PASS" -and $reviewRows.Count -gt 0) {
  "REVIEW_READY"
} else {
  "BLOCKED_DETAIL_UNAVAILABLE"
}

$report = [ordered]@{
  generated_at = $generatedAt.ToString("yyyy-MM-ddTHH:mm:ssZ")
  run_id = $runId
  base_url = $cleanBase
  overall_status = $overall
  mode = $metrics.mode
  production_send = $metrics.production_send
  metrics = [ordered]@{
    truth_observations = $metrics.truth_observations
    truth_review_needed = $metrics.truth_review_needed
    truth_outage_events = $metrics.truth_outage_events
    truth_restore_events = $metrics.truth_restore_events
    truth_open_intervals = $metrics.truth_open_intervals
    truth_closed_intervals = $metrics.truth_closed_intervals
  }
  detail = [ordered]@{
    status = $detailStatus
    error = $detailError
    rows = $reviewRows.Count
    limit = $Limit
  }
  review_rows = $reviewRows
  safety = [ordered]@{
    redaction = "Report uses request ids, hash-derived references, last4, timestamps, and status only. It omits API keys, full meter numbers, PEANO lists, customer identity, room ids, tokens, and raw WebEx/Line text."
    production_send = "blocked"
    truth_source = "AIS outage/restore is the primary truth; Line/WebEx are context only."
  }
}

$jsonPath = Join-Path $OutputDir "open_interval_review_$runId.json"
$mdPath = Join-Path $OutputDir "open_interval_review_$runId.md"

$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$rows = @()
foreach ($row in $reviewRows) {
  $rows += "| $($row.interval_id) | $($row.pair_status) | $($row.outage_request_id) | $($row.outage_at) | $($row.age_hours) | $($row.site_last4) | $($row.meter_last4) | $($row.recommended_action) |"
}
if ($rows.Count -eq 0) {
  $rows += "| none | - | - | - | - | - | - | - |"
}

$markdown = @(
  "# Open Interval Review",
  "",
  "- Generated: $($report.generated_at)",
  "- Overall status: $($report.overall_status)",
  "- API: $($report.base_url)",
  "- Mode: $($report.mode)",
  "- Production send: $($report.production_send)",
  "",
  "## Metrics",
  "",
  "- truth_observations: $($metrics.truth_observations)",
  "- truth_review_needed: $($metrics.truth_review_needed)",
  "- truth_outage_events: $($metrics.truth_outage_events)",
  "- truth_restore_events: $($metrics.truth_restore_events)",
  "- truth_open_intervals: $($metrics.truth_open_intervals)",
  "- truth_closed_intervals: $($metrics.truth_closed_intervals)",
  "- detail_status: $detailStatus",
  "",
  "## Review Queue",
  "",
  "| Interval | Status | Outage request | Outage at | Age hours | Site last4 | Meter last4 | Action |",
  "|---|---|---|---|---:|---|---|---|"
) + $rows + @(
  "",
  "## Decision",
  "",
  "Production customer callback remains blocked. Every open interval must be confirmed as an active outage or explained as a missing restore event before any automatic customer-facing ETR.",
  "",
  "## Safety",
  "",
  "This private report omits API keys, full meter numbers, PEANO lists, customer identity, room ids, tokens, and raw WebEx/Line text."
)

$markdown | Set-Content -LiteralPath $mdPath -Encoding UTF8

$report | ConvertTo-Json -Depth 12
