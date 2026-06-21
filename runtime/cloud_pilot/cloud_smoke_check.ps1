$ErrorActionPreference = "Stop"

param(
  [string]$BaseUrl = "http://127.0.0.1:8090",
  [string]$ApiKey = $env:AIS_INBOUND_API_KEY
)

if (-not $ApiKey) {
  throw "AIS_INBOUND_API_KEY is required in environment or -ApiKey for smoke check."
}

$health = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health" -TimeoutSec 10
if ($health.production_send -ne "blocked") {
  throw "Unsafe health response: production_send=$($health.production_send)"
}

$body = @{
  request_id = "AIS-CLOUD-SMOKE-$(Get-Date -Format yyyyMMddHHmmss)"
  meter_no = "REDACTED-METER-0000"
  timestamp = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
  province = "Sakon Nakhon"
  district = "Phang Khon"
  subdistrict = "Demo"
} | ConvertTo-Json -Depth 4

$response = Invoke-RestMethod -Method POST -Uri "$BaseUrl/api/v1/ais/outage-verifications" -Headers @{
  "Content-Type" = "application/json"
  "X-API-Key" = $ApiKey
} -Body $body -TimeoutSec 20

if ($response.http_status -ne 202 -or $response.production_send -ne "blocked") {
  throw "Unexpected POST response."
}

[pscustomobject]@{
  status = "PASS"
  health = $health.status
  post_status = $response.status
  request_id = $response.request_id
  production_send = $response.production_send
} | ConvertTo-Json -Compress
