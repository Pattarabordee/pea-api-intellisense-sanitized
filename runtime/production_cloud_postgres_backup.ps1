param(
  [string]$WorkspaceRoot = "D:\PEA Intellisense data",
  [string]$DatabaseUrl = $env:DATABASE_URL,
  [string]$OutputDir = "runtime/backups/postgres"
)

$ErrorActionPreference = "Stop"

if (-not $DatabaseUrl) {
  throw "DATABASE_URL is required in environment or -DatabaseUrl. Do not paste it into shared chat."
}

$pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
if (-not $pgDump) {
  throw "pg_dump not found. Install PostgreSQL client tools on the operator machine."
}

$resolvedRoot = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$backupDir = Join-Path $resolvedRoot $OutputDir
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = Join-Path $backupDir "pea_api_intellisense_shadow_$stamp.dump"

& $pgDump.Source --format=custom --no-owner --no-acl --file $backupFile $DatabaseUrl
if ($LASTEXITCODE -ne 0) {
  throw "pg_dump failed"
}

Write-Output "Postgres backup created: $backupFile"
Write-Output "Mode: shadow; production_send: blocked"
