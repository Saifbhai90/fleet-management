# Project-local PATH only (does not change Windows user/machine PATH).
# Usage from repo root in PowerShell:
#   . .\scripts\use_project_env.ps1
# Then: python, pip, pgcli, render  all use .\venv and .\tools\render-cli

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvBin = Join-Path $ProjectRoot "venv\Scripts"
$renderBin = Join-Path $ProjectRoot "tools\render-cli"

if (-not (Test-Path (Join-Path $venvBin "python.exe"))) {
    Write-Warning "venv missing or broken. Create with: py -3.12 -m venv venv   (from repo root), then pip install -r requirements.txt"
}
if (-not (Test-Path (Join-Path $renderBin "render.exe"))) {
    Write-Warning "Render CLI not found under tools\render-cli. Run: .\scripts\download_render_cli.ps1"
}

$env:Path = "$venvBin;$renderBin;$env:Path"
Write-Host "OK: prepended to PATH -> $venvBin" -ForegroundColor Green
Write-Host "    prepended to PATH -> $renderBin" -ForegroundColor Green
