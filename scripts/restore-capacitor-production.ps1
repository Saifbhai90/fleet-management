# Restore Capacitor to live Render URL after LAN testing.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

$bakPath = Join-Path $PWD 'capacitor.config.json.production.bak'
if (-not (Test-Path $bakPath)) {
    Write-Host '[ERROR] capacitor.config.json.production.bak not found.' -ForegroundColor Red
    exit 1
}

Copy-Item $bakPath (Join-Path $PWD 'capacitor.config.json') -Force
Write-Host 'Restored capacitor.config.json from backup.'
npx cap sync android
Write-Host 'Done. Rebuild/install APK to use Render again.'
