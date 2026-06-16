# Point Capacitor Android app at laptop Flask server (LAN dev).
param(
    [string]$Ip = '',
    [int]$Port = 5050
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not $Ip) {
    $Ip = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -like '192.168.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
        Select-Object -First 1 -ExpandProperty IPAddress)
}
if (-not $Ip) {
    Write-Host '[ERROR] Could not detect LAN IP. Pass -Ip 192.168.18.36' -ForegroundColor Red
    exit 1
}

$configPath = Join-Path $PWD 'capacitor.config.json'
$bakPath = Join-Path $PWD 'capacitor.config.json.production.bak'

if (-not (Test-Path $bakPath)) {
    Copy-Item $configPath $bakPath
    Write-Host "Backed up production config -> capacitor.config.json.production.bak"
}

$url = "http://${Ip}:$Port"
$obj = Get-Content $configPath -Raw | ConvertFrom-Json
$obj.server.url = $url
$obj.server.startPath = '/mobile-init'
$obj.server.cleartext = $true
$obj.server.androidScheme = 'http'
$obj | ConvertTo-Json -Depth 10 | Set-Content $configPath -Encoding UTF8

Write-Host ''
Write-Host "Capacitor server.url = $url/mobile-init" -ForegroundColor Cyan
Write-Host 'Running: npx cap sync android ...'
npx cap sync android

Write-Host ''
Write-Host '============================================================' -ForegroundColor Yellow
Write-Host ' ONE-TIME: Open Android Studio and Run app on your phone.' -ForegroundColor Yellow
Write-Host '   npx cap open android'
Write-Host ' After that, HTML/CSS/JS changes on laptop refresh in the app'
Write-Host ' (pull down to refresh; no APK rebuild) while server.url points to your LAN.'
Write-Host ' Look for green banner: DEV LAN · build ... at top of every screen.'
Write-Host ''
Write-Host ' If you still see old UI: Settings > Apps > Fleet Manager > Storage > Clear cache once,'
Write-Host ' then pull down to refresh. Rebuild APK only after native Java changes (MainActivity).'
Write-Host ''
Write-Host ' Restore production Render URL later:'
Write-Host '   Copy-Item capacitor.config.json.production.bak capacitor.config.json'
Write-Host '   npx cap sync android'
Write-Host '============================================================' -ForegroundColor Yellow
