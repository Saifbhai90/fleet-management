# Start Flask for Capacitor LAN testing (same WiFi as phone).
# Fixes silent login failure: SESSION_COOKIE_SECURE must be false on HTTP.
param(
    [int]$Port = 5050
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path 'db\local.db')) {
    Write-Host '[ERROR] db\local.db missing. Run run-local.bat option 2 (FULL SYNC) once first.' -ForegroundColor Red
    exit 1
}

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -like '192.168.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
    Select-Object -First 1 -ExpandProperty IPAddress)

if (-not $ip) {
    $ip = '127.0.0.1'
    Write-Host '[WARN] No 192.168.x.x address found; using 127.0.0.1 (phone cannot reach this).' -ForegroundColor Yellow
}

$env:DATABASE_URL = 'sqlite:///db/local.db'
$env:LOCAL_DB_GUARANTEED = '1'
$env:SESSION_COOKIE_SECURE = 'false'
$env:FLASK_DEBUG = '0'
$env:TEMPLATES_AUTO_RELOAD = '1'
$env:FLEET_MOBILE_DEV = '1'
$env:FLEET_ASSET_VERSION = [string][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$env:PORT = "$Port"

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' LAN server for MOBILE APP testing' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host " URL (phone WebView): http://${ip}:$Port/mobile-init"
Write-Host " Login:               http://${ip}:$Port/login"
Write-Host ' SESSION_COOKIE_SECURE=false (required for HTTP login)'
Write-Host ' DB: db\local.db'
Write-Host ''
Write-Host ' Next: run scripts\point-capacitor-to-lan.ps1 then rebuild APK once.'
Write-Host ' Press Ctrl+C to stop.'
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

python app.py
