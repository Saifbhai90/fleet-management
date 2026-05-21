# Install Fleet Manager APK via USB (adb). Avoid WhatsApp — it corrupts APK files.
param(
    [string]$ApkPath = "..\android\app\build\outputs\apk\release\fleet-manager-1.9.5.apk"
)
$ErrorActionPreference = "Stop"
$full = Resolve-Path $ApkPath
Write-Host "Installing: $full"
adb devices
adb install -r $full
