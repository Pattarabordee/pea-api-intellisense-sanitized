param(
  [Parameter(Mandatory=$true)]
  [string]$BaseUrl,
  [string]$ApiKey = $env:AIS_INBOUND_API_KEY
)

$ErrorActionPreference = "Stop"

if (-not $ApiKey) {
  throw "AIS_INBOUND_API_KEY is required in environment or -ApiKey. Do not paste it into group chat."
}

$cleanBase = $BaseUrl.TrimEnd("/")
$requestId = "AIS-CLOUD-SMOKE-$(Get-Date -Format yyyyMMddHHmmss)"
$headers = @{
  "Content-Type" = "application/json"
  "X-API-Key" = $ApiKey
}

$health = Invoke-RestMethod -Method GET -Uri "$cleanBase/health" -TimeoutSec 15
if ($health.production_send -ne "blocked") {
  throw "Unsafe health response: production_send=$($health.production_send)"
}

$body = @{
  request_id = $requestId
  meter_no = "<REDACTED_METER_REF>"
  timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
  province = "Sakon Nakhon"
  district = "Phang Khon"
  subdistrict = "Demo"
  alarm_type = "AC_MAIN_FAIL"
} | ConvertTo-Json -Depth 5

$first = Invoke-RestMethod -Method POST -Uri "$cleanBase/api/v1/ais/outage-verifications" -Headers $headers -Body $body -TimeoutSec 20
if ($first.http_status -ne 202 -or $first.production_send -ne "blocked" -or $first.duplicate -ne $false) {
  throw "Unexpected first POST response."
}

$duplicate = Invoke-RestMethod -Method POST -Uri "$cleanBase/api/v1/ais/outage-verifications" -Headers $headers -Body $body -TimeoutSec 20
if ($duplicate.http_status -ne 202 -or $duplicate.production_send -ne "blocked" -or $duplicate.duplicate -ne $true) {
  throw "Duplicate request_id did not return duplicate-safe response."
}

$status = Invoke-RestMethod -Method GET -Uri "$cleanBase/api/v1/ais/outage-verifications/$requestId" -Headers @{
  "X-API-Key" = $ApiKey
} -TimeoutSec 20
if ($status.production_send -ne "blocked" -or $status.request_id -ne $requestId) {
  throw "Status lookup did not return safe stored request."
}

$metrics = Invoke-RestMethod -Method GET -Uri "$cleanBase/metrics" -Headers @{
  "X-API-Key" = $ApiKey
} -TimeoutSec 20
if ($metrics.production_send -ne "blocked") {
  throw "Unsafe metrics response: production_send=$($metrics.production_send)"
}

[pscustomobject]@{
  status = "PASS"
  base_url = $cleanBase
  health_status = $health.status
  request_id = $requestId
  first_post = $first.status
  duplicate = $duplicate.duplicate
  status_lookup = $status.status
  total_requests = $metrics.total_requests
  duplicate_callbacks = $metrics.duplicate_callbacks
  pending_worker_traces = $metrics.pending_worker_traces
  production_send = $status.production_send
} | ConvertTo-Json -Depth 5
