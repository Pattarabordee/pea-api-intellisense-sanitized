param(
  [string]$BaseUrl = "https://pea-api-intellisense-api.onrender.com",
  [string]$WebUrl = "https://pea-api-intellisense-web.onrender.com",
  [string]$ApiKey = $env:AIS_INBOUND_API_KEY,
  [int]$Limit = 50,
  [string]$ReportJson = "runtime/production_cloud_real_hit_status.json",
  [string]$ReportMarkdown = "runtime/production_cloud_real_hit_status.md"
)

$ErrorActionPreference = "Stop"

if (-not $ApiKey) {
  throw "AIS_INBOUND_API_KEY is required in environment or -ApiKey. Do not paste it into group chat."
}

$cleanBase = $BaseUrl.TrimEnd("/")
$cleanWeb = $WebUrl.TrimEnd("/")
$headers = @{ "X-API-Key" = $ApiKey }

$health = Invoke-RestMethod -Method GET -Uri "$cleanBase/health" -TimeoutSec 20
if ($health.production_send -ne "blocked") {
  throw "Unsafe health response: production_send=$($health.production_send)"
}

$operator = Invoke-RestMethod -Method GET -Uri "$cleanBase/api/v1/ais/outage-verifications?view=operator&limit=$Limit" -Headers $headers -TimeoutSec 30
if ($operator.production_send -ne "blocked") {
  throw "Unsafe operator response: production_send=$($operator.production_send)"
}

$metrics = Invoke-RestMethod -Method GET -Uri "$cleanBase/metrics" -Headers $headers -TimeoutSec 20
if ($metrics.production_send -ne "blocked") {
  throw "Unsafe metrics response: production_send=$($metrics.production_send)"
}

$items = @($operator.items)
$realItems = @($items | Where-Object {
  $rid = [string]$_.request_id
  $rid -and ($rid -notlike "AIS-CLOUD-SMOKE-*")
})
$latestAny = $items | Select-Object -First 1
$latestReal = $realItems | Select-Object -First 1

$webStatus = "SKIPPED"
$webHasFallback = $false
$webHasLatest = $false
if ($cleanWeb) {
  try {
    $webHtml = curl.exe -sS --max-time 25 "$cleanWeb/"
    $webHasFallback = $webHtml -match "fallback:"
    if ($latestReal) {
      $webHasLatest = $webHtml -match [regex]::Escape([string]$latestReal.request_id)
    } elseif ($latestAny) {
      $webHasLatest = $webHtml -match [regex]::Escape([string]$latestAny.request_id)
    }
    $webStatus = if (-not $webHasFallback -and $webHasLatest) { "PASS" } else { "WARN" }
  } catch {
    $webStatus = "WARN"
  }
}

$status = if ($realItems.Count -gt 0) { "REAL_AIS_HIT_DETECTED" } else { "NO_REAL_AIS_HIT_YET" }
$latest = if ($latestReal) { $latestReal } else { $latestAny }

$latestSummary = $null
if ($latest) {
  $latestSummary = [pscustomobject]@{
    request_id = $latest.request_id
    received_at = $latest.received_at
    status = $latest.status
    callback_status = $latest.callback_status
    production_send = $latest.production_send
  }
}

$report = [pscustomobject]@{
  status = $status
  mode = $health.mode
  production_send = $health.production_send
  api_base_url = $cleanBase
  web_console_url = $cleanWeb
  health_status = $health.status
  database = $health.database
  operator_query = "PASS"
  web_console_live_data = $webStatus
  web_console_has_fallback = $webHasFallback
  total_requests = $metrics.total_requests
  non_smoke_requests = $realItems.Count
  latest_request = $latestSummary
  generated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

$jsonParent = Split-Path -Parent $ReportJson
if ($jsonParent) {
  New-Item -ItemType Directory -Force -Path $jsonParent | Out-Null
}
$mdParent = Split-Path -Parent $ReportMarkdown
if ($mdParent) {
  New-Item -ItemType Directory -Force -Path $mdParent | Out-Null
}

$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportJson -Encoding UTF8

$latestLines = if ($latestSummary) {
  @(
    "- request_id: " + $latestSummary.request_id,
    "- received_at: " + $latestSummary.received_at,
    "- status: " + $latestSummary.status,
    "- callback_status: " + $latestSummary.callback_status,
    "- production_send: " + $latestSummary.production_send
  )
} else {
  @("- none")
}

$markdown = @(
  "# Production Cloud Real Hit Status",
  "",
  "- Status: " + $report.status,
  "- Mode: " + $report.mode,
  "- Production send: " + $report.production_send,
  "- API: " + $report.api_base_url,
  "- Web console: " + $report.web_console_url,
  "- Health: " + $report.health_status,
  "- Database: " + $report.database,
  "- Operator query: " + $report.operator_query,
  "- Web console live data: " + $report.web_console_live_data,
  "- Total requests: " + $report.total_requests,
  "- Non-smoke requests: " + $report.non_smoke_requests,
  "",
  "## Latest Redacted Request",
  ""
) + $latestLines + @(
  "",
  "## Safety",
  "",
  "This report intentionally omits API keys, full meter numbers, PEANO lists, customer identity, DB URLs, and verbatim WebEx text."
)
$markdown | Set-Content -LiteralPath $ReportMarkdown -Encoding UTF8

$report | ConvertTo-Json -Depth 8
