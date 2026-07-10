param(
  [Parameter(Mandatory=$true)]
  [string]$BaseUrl,
  [string]$ApiKey = $env:AIS_INBOUND_API_KEY
)

$ErrorActionPreference = "Stop"
if (-not $ApiKey) {
  throw "AIS_INBOUND_API_KEY is required in environment or -ApiKey."
}

$cleanBase = $BaseUrl.TrimEnd("/")
$headers = @{ "X-API-Key" = $ApiKey }
$health = Invoke-RestMethod -Method GET -Uri "$cleanBase/health" -TimeoutSec 15
$metrics = Invoke-RestMethod -Method GET -Uri "$cleanBase/metrics" -Headers $headers -TimeoutSec 20
$intervals = Invoke-RestMethod -Method GET -Uri "$cleanBase/api/v1/ais/truth-intervals?status=ALL&limit=5" -Headers $headers -TimeoutSec 20

foreach ($surface in @($health, $metrics, $intervals)) {
  if ($surface.production_send -ne "blocked") {
    throw "Unsafe response: production_send=$($surface.production_send)"
  }
}

[pscustomobject]@{
  status = "PASS_READ_ONLY"
  base_url = $cleanBase
  health_status = $health.status
  total_requests = $metrics.total_requests
  truth_meter_state_intervals = $metrics.truth_meter_state_intervals
  model_ready_clean_truth_rows = $metrics.model_ready_clean_truth_rows
  interval_rows_sampled = $intervals.count
  production_send = $metrics.production_send
} | ConvertTo-Json -Depth 5
