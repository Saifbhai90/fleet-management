# Bump android/version.properties (VERSION_CODE +1, VERSION_NAME patch/minor/major).
# Usage: .\scripts\bump-android-version.ps1
#        .\scripts\bump-android-version.ps1 -Part minor

param(
    [ValidateSet('patch', 'minor', 'major')]
    [string]$Part = 'patch'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$propsPath = Join-Path $root 'android\version.properties'

if (-not (Test-Path $propsPath)) {
    Write-Error "Missing $propsPath"
}

$lines = Get-Content $propsPath
$code = 1
$name = '1.0.0'
foreach ($line in $lines) {
    if ($line -match '^\s*VERSION_CODE\s*=\s*(\d+)\s*$') { $code = [int]$Matches[1] }
    if ($line -match '^\s*VERSION_NAME\s*=\s*(\S+)\s*$') { $name = $Matches[1] }
}

if ($name -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
    Write-Error "VERSION_NAME must be X.Y.Z (current: $name)"
}
$major = [int]$Matches[1]
$minor = [int]$Matches[2]
$patch = [int]$Matches[3]

switch ($Part) {
    'major' { $major++; $minor = 0; $patch = 0 }
    'minor' { $minor++; $patch = 0 }
    'patch' { $patch++ }
}
$newCode = $code + 1
$newName = "$major.$minor.$patch"

$out = @(
    '# Single source for Android app version (Gradle reads this on every build).',
    '# Bump: npm run version:bump   OR edit VERSION_CODE (+1) and VERSION_NAME below.',
    "VERSION_CODE=$newCode",
    "VERSION_NAME=$newName"
)
Set-Content -Path $propsPath -Value $out -Encoding UTF8

$pkgJson = Join-Path $root 'package.json'
if (Test-Path $pkgJson) {
    $json = Get-Content $pkgJson -Raw | ConvertFrom-Json
    $json.version = $newName
    ($json | ConvertTo-Json -Depth 10) + "`n" | Set-Content -Path $pkgJson -Encoding UTF8 -NoNewline
}

Write-Host "Android version: $name (code $code) -> $newName (code $newCode)"
Write-Host "APK output name: fleet-manager-$newName.apk"
Write-Host "Next: Android Studio -> Sync Gradle -> Rebuild"
