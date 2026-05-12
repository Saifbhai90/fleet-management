# Downloads official Render CLI (Windows amd64) into .\tools\render-cli\
# Run from repo root:  powershell -ExecutionPolicy Bypass -File .\scripts\download_render_cli.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$dest = Join-Path $ProjectRoot "tools\render-cli"
$version = "v2.16.0"
$zipName = "cli_2.16.0_windows_amd64.zip"
$url = "https://github.com/render-oss/cli/releases/download/$version/$zipName"

New-Item -ItemType Directory -Force -Path $dest | Out-Null
$zip = Join-Path $env:TEMP $zipName
Write-Host "Downloading $url ..."
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $dest -Force
Remove-Item $zip -Force
Copy-Item (Join-Path $dest "cli_v2.16.0.exe") (Join-Path $dest "render.exe") -Force
Write-Host "Done. render.exe -> $dest" -ForegroundColor Green
