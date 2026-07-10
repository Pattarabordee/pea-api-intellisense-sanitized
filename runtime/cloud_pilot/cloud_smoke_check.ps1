param(
  [string]$BaseUrl = "http://127.0.0.1:8090",
  [string]$ApiKey = $env:AIS_INBOUND_API_KEY
)

$ErrorActionPreference = "Stop"

if (-not $ApiKey) {
  throw "AIS_INBOUND_API_KEY is required in environment or -ApiKey for read-only smoke check."
}

$cleanBase = $BaseUrl.TrimEnd("/")
$headers = @{ "X-API-Key" = $ApiKey }

$health = Invoke-RestMethod -Method GET -Uri "$cleanBase/health" -TimeoutSec 10
$metrics = Invoke-RestMethod -Method GET -Uri "$cleanBase/metrics" -Headers $headers -TimeoutSec 20
$intervals = Invoke-RestMethod -Method GET -Uri "$cleanBase/api/v1/ais/truth-intervals?status=ALL&limit=1" -Headers $headers -TimeoutSec 20

foreach ($item in @($health, $metrics, $intervals)) {
  if ($item.production_send -ne "blocked") {
    throw "Unsafe response: production_send=$($item.production_send)"
  }
}

[pscustomobject]@{
  status = "PASS"
  method_policy = "GET_ONLY"
  health = $health.status
  semantic_mapping_version = $metrics.semantic_mapping_version
  model_ready_clean_truth_rows = $metrics.model_ready_clean_truth_rows
  interval_endpoint = "PASS"
  production_send = "blocked"
} | ConvertTo-Json -Compress
