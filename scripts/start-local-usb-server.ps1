# Local Flask for the USB Capacitor app (127.0.0.1:5050 + adb reverse).
param(
    [int]$Port = 5050
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$Host.UI.RawUI.WindowTitle = "Fleet Local Server :$Port"

if (-not (Test-Path 'db\local.db')) {
    Write-Host '[ERROR] db\local.db missing. Pehle run-local.bat option 1/2 chalao.' -ForegroundColor Red
    Read-Host 'Enter dabao'
    exit 1
}

$env:DATABASE_URL = 'sqlite:///db/local.db'
$env:LOCAL_DB_GUARANTEED = '1'
$env:SESSION_COOKIE_SECURE = 'false'
$env:FLASK_DEBUG = '0'
$env:TEMPLATES_AUTO_RELOAD = '1'
$env:FLEET_MOBILE_DEV = '1'
$env:LOCAL_FAST_BOOT = '1'
$env:SKIP_STARTUP_TASKS = '1'
$env:FLEET_ASSET_VERSION = [string][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$env:PORT = "$Port"

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host " Fleet Local Server  http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host ' USB app isi window ke through phone pe khulti hai.' -ForegroundColor Green
Write-Host ' Band mat karo jab tak phone use kar rahe ho.' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

python app.py
