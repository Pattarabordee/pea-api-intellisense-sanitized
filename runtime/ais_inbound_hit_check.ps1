param(
  [string]$RequestsLog = "runtime/private/ais_inbound_requests.jsonl",
  [int]$Tail = 20
)

$ErrorActionPreference = "Stop"

function Request-Ref([string]$Value) {
  if (-not $Value) { return $null }
  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [System.Text.Encoding]::UTF8.GetBytes("request|$Value")
    $hash = [System.BitConverter]::ToString($sha.ComputeHash($bytes)).Replace("-", "").ToLowerInvariant()
    return "request_$($hash.Substring(0,16))"
  } finally {
    $sha.Dispose()
  }
}

if (-not (Test-Path -LiteralPath $RequestsLog)) {
  [pscustomobject]@{ status="NO_REQUEST_LOG"; total_requests=0; non_smoke_requests=0; production_send="blocked" } | ConvertTo-Json
  exit 0
}

$rows = @(Get-Content -LiteralPath $RequestsLog | Where-Object { $_.Trim() } | ForEach-Object {
  try { $_ | ConvertFrom-Json } catch { $null }
} | Where-Object { $_ -ne $null })
$smokePrefixes = @("AIS-CONNECTIVITY-","AIS-IP-CHECK-","AIS-SMOKE-","AIS-PUBLIC-","AIS-FINAL-","AIS-BEARER-","AIS-DEMO-","AIS-CODEX-")
$nonSmoke = @($rows | Where-Object {
  $rid = [string]$_.accepted_response.request_id
  if (-not $rid) { return $false }
  foreach ($prefix in $smokePrefixes) { if ($rid.StartsWith($prefix, [System.StringComparison]::Ordinal)) { return $false } }
  return $true
})
$recent = @($rows | Select-Object -Last $Tail | ForEach-Object {
  [pscustomobject]@{ received_at=$_.received_at; request_ref=(Request-Ref $_.accepted_response.request_id); status=$_.accepted_response.status; callback_status=$_.callback_status }
})
[pscustomobject]@{
  status="OK"
  total_requests=$rows.Count
  non_smoke_requests=$nonSmoke.Count
  latest_non_smoke_request_ref=if($nonSmoke.Count){Request-Ref $nonSmoke[-1].accepted_response.request_id}else{$null}
  recent=$recent
  production_send="blocked"
} | ConvertTo-Json -Depth 6
