param(
  [string]$BaseUrl = "https://pea-api-intellisense-api.onrender.com",
  [string]$ApiKey = $env:AIS_INBOUND_API_KEY,
  [int]$Limit = 50,
  [string]$ReportJson = "runtime/private/production_cloud_real_hit_status.json",
  [string]$ReportMarkdown = "runtime/private/production_cloud_real_hit_status.md",
  [switch]$SelfTest
)

$ErrorActionPreference = "Stop"

function Get-RedactedRequestRef {
  param([string]$RequestId)

  if (-not $RequestId) {
    return $null
  }
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($RequestId)
  $sha256 = [System.Security.Cryptography.SHA256]::Create()
  try {
    $hex = [System.BitConverter]::ToString($sha256.ComputeHash($bytes)).Replace("-", "").ToLowerInvariant()
  } finally {
    $sha256.Dispose()
  }
  return "request_" + $hex.Substring(0, 16)
}

if ($SelfTest) {
  if ((Get-RedactedRequestRef -RequestId "abc") -ne "request_ba7816bf8f01cfea") {
    throw "Redacted request reference self-test failed"
  }
  if (Get-RedactedRequestRef -RequestId "") {
    throw "Empty request reference must stay empty"
  }
  return
}

if (-not $ApiKey) {
  throw "AIS_INBOUND_API_KEY is required in environment or -ApiKey. Do not paste it into group chat."
}

$cleanBase = $BaseUrl.TrimEnd("/")
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
$smokePrefixes = @(
  "AIS-CLOUD-SMOKE-",
  "AIS-SMOKE-",
  "AIS-PUBLIC-ALIAS-SMOKE-",
  "AIS-FINAL-LOCAL-SMOKE-",
  "AIS-BEARER-SMOKE-",
  "AIS-DEMO-SHADOW-",
  "AIS-CODEX-"
)
$itemsWithRawRequestId = @($items | Where-Object { [string]$_.request_id })
$operatorIdentifierVisibility = if ($itemsWithRawRequestId.Count -gt 0) { "RAW_REQUEST_ID_VISIBLE" } else { "REDACTED_REQUEST_REF_ONLY" }
$realItems = @()
if ($itemsWithRawRequestId.Count -gt 0) {
  $realItems = @($itemsWithRawRequestId | Where-Object {
    $rid = [string]$_.request_id
    foreach ($prefix in $smokePrefixes) {
      if ($rid.StartsWith($prefix, [System.StringComparison]::Ordinal)) {
        return $false
      }
    }
    return $true
  })
}
$latestAny = $items | Select-Object -First 1
$latestReal = $realItems | Select-Object -First 1

$status = if ($itemsWithRawRequestId.Count -eq 0) {
  if ($items.Count -gt 0) { "REDACTED_OPERATOR_ITEMS_CAPTURED" } else { "NO_OPERATOR_ITEMS" }
} elseif ($realItems.Count -gt 0) {
  "REAL_AIS_HIT_DETECTED"
} else {
  "NO_REAL_AIS_HIT_YET"
}
$latest = if ($latestReal) { $latestReal } else { $latestAny }

$latestSummary = $null
if ($latest) {
  $requestRef = [string]$latest.request_ref
  if ($requestRef -notmatch '^request_[a-f0-9]{16}$') {
    $requestRef = Get-RedactedRequestRef -RequestId ([string]$latest.request_id)
  }
  $latestSummary = [pscustomobject]@{
    request_ref = $requestRef
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
  health_status = $health.status
  database = $health.database
  operator_query = "PASS"
  operator_identifier_visibility = $operatorIdentifierVisibility
  public_console_check = "SKIPPED_DEMO_ISOLATED"
  total_requests = $metrics.total_requests
  non_smoke_requests = if ($itemsWithRawRequestId.Count -gt 0) { $realItems.Count } else { $null }
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
    "- request_ref: " + $latestSummary.request_ref,
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
  "- Health: " + $report.health_status,
  "- Database: " + $report.database,
  "- Operator query: " + $report.operator_query,
  "- Operator identifier visibility: " + $report.operator_identifier_visibility,
  "- Public console check: " + $report.public_console_check,
  "- Total requests: " + $report.total_requests,
  "- Non-smoke requests: " + $(if ($null -eq $report.non_smoke_requests) { "not available from redacted endpoint" } else { $report.non_smoke_requests }),
  "",
  "## Latest Redacted Request",
  ""
) + $latestLines + @(
  "",
  "## Safety",
  "",
  "This report intentionally omits API keys, raw request IDs, full meter numbers, PEANO lists, customer identity, DB URLs, and verbatim WebEx text."
)
$markdown | Set-Content -LiteralPath $ReportMarkdown -Encoding UTF8

$report | ConvertTo-Json -Depth 8
