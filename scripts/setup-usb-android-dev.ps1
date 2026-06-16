# USB cable dev: phone loads laptop Flask via adb reverse (no Wi-Fi needed).
param(
    [int]$Port = 5050
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

$adb = @(
    "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
    "${env:ProgramFiles}\Android\Android Studio\platform-tools\adb.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $adb) {
    Write-Host '[ERROR] adb.exe not found. Install Android SDK platform-tools.' -ForegroundColor Red
    exit 1
}

$devices = & $adb devices | Select-String 'device$' | Where-Object { $_ -notmatch 'List of devices' }
if (-not $devices) {
    Write-Host '[ERROR] No phone connected. Enable USB debugging and accept the RSA prompt.' -ForegroundColor Red
    exit 1
}

Write-Host "Using adb: $adb" -ForegroundColor Cyan
& $adb reverse --remove-all 2>$null
& $adb reverse "tcp:$Port" "tcp:$Port"
Write-Host "adb reverse: phone 127.0.0.1:$Port -> laptop 127.0.0.1:$Port" -ForegroundColor Green

$configPath = Join-Path $PWD 'capacitor.config.json'
$bakPath = Join-Path $PWD 'capacitor.config.json.production.bak'
if (-not (Test-Path $bakPath)) {
    Copy-Item $configPath $bakPath
    Write-Host "Backed up production config -> capacitor.config.json.production.bak"
}

$url = "http://127.0.0.1:$Port"
$obj = Get-Content $configPath -Raw | ConvertFrom-Json
$obj.server.url = $url
$obj.server.startPath = '/mobile-init'
$obj.server.cleartext = $true
$obj.server.androidScheme = 'http'
if (-not $obj.server.PSObject.Properties['allowNavigation']) {
    $obj.server | Add-Member -NotePropertyName allowNavigation -NotePropertyValue @('127.0.0.1', 'localhost', '192.168.18.36', '192.168.18.15')
} else {
    $obj.server.allowNavigation = @('127.0.0.1', 'localhost', '192.168.18.36', '192.168.18.15')
}
$obj | ConvertTo-Json -Depth 10 | Set-Content $configPath -Encoding UTF8

Write-Host ''
Write-Host "Capacitor server.url = $url/mobile-init (USB)" -ForegroundColor Cyan

# Stop any stale Flask on this port (plain python app.py serves OLD cached templates).
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

Write-Host "Starting LAN server on port $Port ..."
Start-Process powershell -ArgumentList @(
    '-NoExit', '-ExecutionPolicy', 'Bypass',
    '-File', (Join-Path $PWD 'scripts\start-lan-for-mobile.ps1'),
    '-Port', "$Port"
) -WindowStyle Minimized

Start-Sleep -Seconds 8
try {
    $code = (Invoke-WebRequest -Uri "http://127.0.0.1:$Port/login" -UseBasicParsing -TimeoutSec 15).StatusCode
    Write-Host "Server OK (HTTP $code)" -ForegroundColor Green
} catch {
    Write-Host '[WARN] Server not ready yet - wait 10s and try Run in Android Studio.' -ForegroundColor Yellow
}

Write-Host 'Running: npx cap sync android ...'
npx cap sync android

Write-Host ''
Write-Host '============================================================' -ForegroundColor Yellow
Write-Host ' Next: Android Studio -> Run on your phone (USB connected).'
Write-Host ' Server is started automatically by this script (do not run plain python app.py).'
Write-Host ' After login you MUST see green banner: DEV - build ...'
Write-Host ' If banner missing, app is still on old/production build - Run again.'
Write-Host '============================================================' -ForegroundColor Yellow
