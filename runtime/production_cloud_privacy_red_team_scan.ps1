param(
  [string]$WorkspaceRoot = "D:\PEA Intellisense data",
  [string[]]$ScanRoots = @("runtime/github_sanitized_source", "runtime/chatgpt_production_review"),
  [string]$ReportJson = "runtime/production_cloud_privacy_red_team_scan_report.json",
  [string]$ReportMarkdown = "runtime/production_cloud_privacy_red_team_scan_report.md"
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$patterns = @(
  @{ name = "openai_key"; regex = "sk-[A-Za-z0-9_\-]{12,}" },
  @{ name = "webex_room_id"; regex = "Y2lzY29zcGFyazovL3VzL1JPT00v[A-Za-z0-9_\-=]+" },
  @{ name = "local_tunnel_url"; regex = "https://[A-Za-z0-9\-]+\.loca\.lt" },
  @{ name = "json_secret_value"; regex = "(?i)""(?:access_token|refresh_token|client_secret|api_key|x-api-key|token|secret)""\s*:\s*""(?!<REDACTED)[^""]+""" },
  @{ name = "raw_meter_json"; regex = "(?i)""(?:meter_no|peano|meterNumber|meterNo)""\s*:\s*""[0-9]{6,}""" }
)

$findings = New-Object System.Collections.Generic.List[object]

foreach ($scanRoot in $ScanRoots) {
  $path = Join-Path $root $scanRoot
  if (-not (Test-Path -LiteralPath $path)) {
    continue
  }
  $resolvedPath = (Resolve-Path -LiteralPath $path).Path
  if (-not $resolvedPath.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to scan outside workspace: $resolvedPath"
  }
  Get-ChildItem -LiteralPath $resolvedPath -Recurse -File |
    Where-Object { $_.Length -le 3000000 } |
    ForEach-Object {
      $relative = $_.FullName.Substring($root.Length + 1)
      $text = Get-Content -Raw -Encoding UTF8 -LiteralPath $_.FullName -ErrorAction SilentlyContinue
      foreach ($pattern in $patterns) {
        if ($text -match $pattern.regex) {
          $findings.Add([pscustomobject]@{
            file = $relative
            issue = $pattern.name
          })
        }
      }
    }
}

$status = if ($findings.Count -eq 0) { "PASS" } else { "FAIL" }
$report = [pscustomobject]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  mode = "shadow"
  production_send = "blocked"
  status = $status
  findings = $findings
}

$jsonPath = Join-Path $root $ReportJson
$mdPath = Join-Path $root $ReportMarkdown
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Production Cloud Privacy Red-Team Scan")
$lines.Add("")
$lines.Add('- Mode: `shadow`')
$lines.Add('- Production send: `blocked`')
$lines.Add(('- Status: `{0}`' -f $status))
$lines.Add(('- Scan roots: `{0}`' -f ($ScanRoots -join ', ')))
$lines.Add("")
if ($findings.Count -eq 0) {
  $lines.Add("No forbidden secret/customer patterns found in sanitized review roots.")
} else {
  foreach ($finding in $findings) {
    $lines.Add(('- FAIL `{0}` in `{1}`' -f $finding.issue, $finding.file))
  }
}
$lines | Set-Content -LiteralPath $mdPath -Encoding UTF8

if ($status -ne "PASS") {
  throw "Privacy red-team scan failed. See $mdPath"
}

Write-Output "Privacy red-team scan PASS. Report: $mdPath"
