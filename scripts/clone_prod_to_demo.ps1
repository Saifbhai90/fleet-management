# Clone production Postgres → demo Postgres (full logical dump).
# Usage:
#   $env:DEMO_DATABASE_URL = "postgresql://...@dpg-....singapore-postgres.render.com/fleet_demo_db"
#   powershell -File scripts/clone_prod_to_demo.ps1
#
# Reads production URL from repo-root .env (DATABASE_URL).
# NEVER point DEMO_DATABASE_URL at production.

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Read-DotEnvUrl([string]$path, [string]$key) {
    if (-not (Test-Path $path)) { return $null }
    foreach ($line in Get-Content $path) {
        if ($line -match "^\s*$key\s*=\s*(.+)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function Normalize-PgUrl([string]$url) {
    if ([string]::IsNullOrWhiteSpace($url)) { return $url }
    return $url -replace '^postgres://', 'postgresql://'
}

$ProdUrl = Normalize-PgUrl (Read-DotEnvUrl (Join-Path $Root '.env') 'DATABASE_URL')
$DemoUrl = Normalize-PgUrl ($env:DEMO_DATABASE_URL)

if (-not $ProdUrl) { throw 'Production DATABASE_URL not found in .env' }
if (-not $DemoUrl) { throw 'Set DEMO_DATABASE_URL to fleet-demo-db External Database URL first' }

if ($DemoUrl -match 'company_management_w27v' -or $DemoUrl -eq $ProdUrl) {
    throw 'Refusing to restore onto production URL'
}
if ($ProdUrl -notmatch 'dpg-d6k6omn5r7bs73a8crcg-a' -and $ProdUrl -notmatch 'company_management') {
    Write-Warning 'Production URL does not look like the known Render prod DB — double-check .env'
}

$PgBinCandidates = @(
    'C:\Program Files\PostgreSQL\18\bin',
    'C:\Program Files\PostgreSQL\17\bin',
    'C:\Program Files\PostgreSQL\16\bin',
    'C:\Program Files\PostgreSQL\15\bin',
    'C:\Program Files\PostgreSQL\14\bin'
)
foreach ($bin in $PgBinCandidates) {
    if (Test-Path (Join-Path $bin 'pg_dump.exe')) {
        $env:Path = "$bin;$env:Path"
        break
    }
}
$PgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
$PgRestore = Get-Command pg_restore -ErrorAction SilentlyContinue
if (-not $PgDump -or -not $PgRestore) {
    throw 'pg_dump/pg_restore not found. Install PostgreSQL client tools and reopen the shell.'
}

$DumpDir = Join-Path $Root 'tmp'
New-Item -ItemType Directory -Force -Path $DumpDir | Out-Null
$ReuseDump = Join-Path $DumpDir 'prod_to_demo_latest.dump'
if ($env:DEMO_REUSE_DUMP -eq '1' -and (Test-Path $ReuseDump) -and ((Get-Item $ReuseDump).Length -gt 1MB)) {
    $DumpFile = $ReuseDump
    Write-Host "=== Reusing existing dump: $DumpFile ==="
} else {
    $DumpFile = Join-Path $DumpDir ("prod_to_demo_{0:yyyyMMdd_HHmmss}.dump" -f (Get-Date))
    Write-Host "=== Dumping production (~1.5GB, may take 20-60+ min) ==="
    Write-Host "Target dump: $DumpFile"
    & $PgDump.Source --format=custom --no-owner --no-acl --verbose --dbname=$ProdUrl --file=$DumpFile
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed: $LASTEXITCODE" }
    Copy-Item $DumpFile $ReuseDump -Force
}

Write-Host "=== Restoring into demo (CLEAN — replaces demo schema) ==="
& $PgRestore.Source --verbose --clean --if-exists --no-owner --no-acl --dbname=$DemoUrl $DumpFile
# pg_restore often exits 1 on benign errors (role missing etc.)
Write-Host "pg_restore exit: $LASTEXITCODE"

Write-Host "=== Ensuring Master login demo / Demo#2026 on demo DB ==="
$env:DATABASE_URL = $DemoUrl
$env:DEMO_MODE = '1'
python -c "from services.demo_env import seed_demo_data; print(seed_demo_data())"

Write-Host "=== Done ==="
Write-Host "1) Set fleet-demo DATABASE_URL to the Internal URL (same password, internal host)."
Write-Host "2) Redeploy fleet-demo."
Write-Host "3) Login: demo / Demo#2026 (Master)"
Write-Host "Dump kept at: $DumpFile (delete when finished)"
