param(
  [string]$WorkspaceRoot = "D:\PEA Intellisense data",
  [switch]$RequireGo,
  [string]$ReportJson = "runtime/production_cloud_local_qa_report.json",
  [string]$ReportMarkdown = "runtime/production_cloud_local_qa_report.md"
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $WorkspaceRoot

$results = New-Object System.Collections.Generic.List[object]

function Add-Result {
  param(
    [string]$Name,
    [string]$Status,
    [string]$Detail
  )
  $results.Add([pscustomobject]@{
    name = $Name
    status = $Status
    detail = $Detail
  })
}

function Invoke-QACheck {
  param(
    [string]$Name,
    [scriptblock]$Block
  )
  try {
    & $Block
    Add-Result -Name $Name -Status "PASS" -Detail "completed"
  } catch {
    Add-Result -Name $Name -Status "FAIL" -Detail $_.Exception.Message
  }
}

Invoke-QACheck -Name "python_guardrails" -Block {
  $env:PYTHONPATH = $WorkspaceRoot
  python tests\test_production_path.py | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "tests/test_production_path.py failed" }
  python tests\test_ais_inbound.py | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "tests/test_ais_inbound.py failed" }
}

if (Get-Command go -ErrorAction SilentlyContinue) {
  Invoke-QACheck -Name "go_api_tests" -Block {
    Push-Location -LiteralPath (Join-Path $WorkspaceRoot "apps/api-go")
    try {
      go test ./... | Out-Host
      if ($LASTEXITCODE -ne 0) { throw "go test failed" }
      go vet ./... | Out-Host
      if ($LASTEXITCODE -ne 0) { throw "go vet failed" }
    } finally {
      Pop-Location
    }
  }
} elseif ($RequireGo) {
  Add-Result -Name "go_api_tests" -Status "FAIL" -Detail "Go CLI not found; install Go 1.23+ or run GitHub Actions."
} else {
  Add-Result -Name "go_api_tests" -Status "WARN" -Detail "Go CLI not found locally; GitHub Actions runs this lane."
}

if (Get-Command npm -ErrorAction SilentlyContinue) {
  Invoke-QACheck -Name "next_console_build" -Block {
    Push-Location -LiteralPath (Join-Path $WorkspaceRoot "apps/web-next")
    try {
      npm ci | Out-Host
      if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
      npm audit --audit-level=moderate | Out-Host
      if ($LASTEXITCODE -ne 0) { throw "npm audit failed" }
      npm run build | Out-Host
      if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    } finally {
      Pop-Location
    }
  }
} else {
  Add-Result -Name "next_console_build" -Status "FAIL" -Detail "npm not found"
}

Invoke-QACheck -Name "sanitized_export_scan" -Block {
  $env:PYTHONPATH = $WorkspaceRoot
  python -m ais_etr export-sanitized-codebase | Out-Host
  if ($LASTEXITCODE -ne 0) { throw "sanitized export command failed" }
  $manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $WorkspaceRoot "runtime/sanitized_codebase_manifest.json") | ConvertFrom-Json
  if ($manifest.status -ne "PASS") { throw "sanitized export status=$($manifest.status)" }
}

$overall = "PASS"
if ($results | Where-Object { $_.status -eq "FAIL" }) {
  $overall = "FAIL"
} elseif ($results | Where-Object { $_.status -eq "WARN" }) {
  $overall = "WARN"
}

$report = [pscustomobject]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  mode = "shadow"
  production_send = "blocked"
  overall_status = $overall
  results = $results
}

$jsonPath = Join-Path $WorkspaceRoot $ReportJson
$mdPath = Join-Path $WorkspaceRoot $ReportMarkdown
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Production Cloud Local QA")
$lines.Add("")
$lines.Add('- Mode: `shadow`')
$lines.Add('- Production send: `blocked`')
$lines.Add(('- Overall: `{0}`' -f $overall))
$lines.Add("")
foreach ($item in $results) {
  $lines.Add(('- {0} `{1}`: {2}' -f $item.status, $item.name, $item.detail))
}
$lines | Set-Content -LiteralPath $mdPath -Encoding UTF8

if ($overall -eq "FAIL") {
  throw "Production cloud local QA failed. See $mdPath"
}

Write-Output "Production cloud local QA $overall. Report: $mdPath"
