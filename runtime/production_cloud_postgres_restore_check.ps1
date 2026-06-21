param(
  [Parameter(Mandatory=$true)]
  [string]$BackupFile,
  [string]$RestoreDatabaseUrl = $env:RESTORE_TEST_DATABASE_URL
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $BackupFile)) {
  throw "Backup file not found: $BackupFile"
}
if (-not $RestoreDatabaseUrl) {
  throw "RESTORE_TEST_DATABASE_URL is required. Never run restore check against the production database."
}
if ($env:DATABASE_URL -and $RestoreDatabaseUrl -eq $env:DATABASE_URL) {
  throw "Restore target equals DATABASE_URL. Refusing to restore into production."
}

$pgRestore = Get-Command pg_restore -ErrorAction SilentlyContinue
$psql = Get-Command psql -ErrorAction SilentlyContinue
if (-not $pgRestore) { throw "pg_restore not found. Install PostgreSQL client tools." }
if (-not $psql) { throw "psql not found. Install PostgreSQL client tools." }

& $pgRestore.Source --clean --if-exists --no-owner --no-acl --dbname $RestoreDatabaseUrl $BackupFile
if ($LASTEXITCODE -ne 0) {
  throw "pg_restore failed"
}

& $psql.Source $RestoreDatabaseUrl -v "ON_ERROR_STOP=1" -c "select count(*) as ais_inbound_requests from ais_inbound_requests;" | Out-Host
if ($LASTEXITCODE -ne 0) {
  throw "restore validation query failed"
}

Write-Output "Restore check passed. Mode: shadow; production_send: blocked"
