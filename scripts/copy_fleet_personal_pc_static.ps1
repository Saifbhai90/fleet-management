# After npm run build in daedalOS (with FLEET_OS_BASE_PATH), copy Next export into Flask static.
$repoRoot = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repoRoot 'daedalOS\out'
$dst = Join-Path $repoRoot 'static\fleet_personal_pc'
$idx = Join-Path $src 'index.html'
if (-not (Test-Path $idx)) {
  Write-Error 'Missing daedalOS/out/index.html - run daedalOS build first (see daedalOS/FLEET_EMBED.md).'
  exit 1
}
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Get-ChildItem $dst -Exclude 'README.txt' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -Path (Join-Path $src '*') -Destination $dst -Recurse -Force
$bytes = (Get-ChildItem $dst -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
Write-Host ('Copied daedalOS/out -> static/fleet_personal_pc ({0} bytes)' -f $bytes)
