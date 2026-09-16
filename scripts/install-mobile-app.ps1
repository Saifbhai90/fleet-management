# One-click USB install: Local (Flask + debug APK) or Online (Render URL + debug APK).
# Always uninstalls com.fleetmanager.app first, then installs the current
# android/version.properties build. Incremental Gradle — no clean.
param(
    [ValidateSet('Local', 'Online')]
    [string]$Mode = 'Local',

    [int]$Port = 5050,

    [switch]$ForceSync,
    [switch]$CreateShortcuts,
    [switch]$Pause
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

$AppId = 'com.fleetmanager.app'
$LaunchActivity = 'com.fleetmanager.app/.MainActivity'
$ConfigPath = Join-Path $RepoRoot 'capacitor.config.json'
$BakPath = Join-Path $RepoRoot 'capacitor.config.json.production.bak'
$LocalTemplate = Join-Path $PSScriptRoot 'capacitor.local.usb.json'
$AssetsConfig = Join-Path $RepoRoot 'android\app\src\main\assets\capacitor.config.json'
$DebugManifest = Join-Path $RepoRoot 'android\app\src\debug\AndroidManifest.xml'
$VersionProps = Join-Path $RepoRoot 'android\version.properties'
$LocalUrl = "http://127.0.0.1:$Port"

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "    $Message" -ForegroundColor Yellow
}

function Get-JsonServerUrl([string]$Path) {
    if (-not (Test-Path $Path)) { return '' }
    try {
        $obj = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        return ([string]$obj.server.url).Trim().TrimEnd('/')
    } catch {
        return ''
    }
}

function Get-AppVersionLabel {
    $code = '?'
    $name = '?'
    if (Test-Path $VersionProps) {
        foreach ($line in Get-Content -LiteralPath $VersionProps) {
            if ($line -match '^\s*VERSION_CODE\s*=\s*(\d+)\s*$') { $code = $Matches[1] }
            if ($line -match '^\s*VERSION_NAME\s*=\s*(\S+)\s*$') { $name = $Matches[1] }
        }
    }
    return "$name (code $code)"
}

function Get-AdbPath {
    $candidates = @(
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
        $(if ($env:ANDROID_HOME) { Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe' } else { $null }),
        "${env:ProgramFiles}\Android\Android Studio\platform-tools\adb.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }
    if (-not $candidates) {
        throw 'adb.exe nahi mila. Android SDK platform-tools install karo.'
    }
    return $candidates[0]
}

function Set-AndroidBuildEnv {
    $jbr = 'C:\Program Files\Android\Android Studio\jbr'
    if (Test-Path (Join-Path $jbr 'bin\java.exe')) {
        $env:JAVA_HOME = $jbr
    } elseif (-not $env:JAVA_HOME) {
        throw 'JAVA_HOME nahi mila. Android Studio JBR chahiye.'
    }
    if (-not $env:ANDROID_HOME -or -not (Test-Path $env:ANDROID_HOME)) {
        $sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
        if (Test-Path $sdk) { $env:ANDROID_HOME = $sdk }
    }
    $env:Path = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:Path"
}

function Get-PhoneSerial([string]$Adb) {
    $rows = & $Adb devices
    $ready = @($rows | Where-Object { $_ -match '^\S+\s+device$' })
    $unauthorized = @($rows | Where-Object { $_ -match 'unauthorized' })
    if ($unauthorized) {
        throw 'Phone USB debugging accept nahi hua. Phone pe Allow dabao, phir dubara run karo.'
    }
    if (-not $ready) {
        throw 'Koi phone connected nahi. USB + File Transfer + USB debugging ON rakho.'
    }
    return ($ready[0] -split '\s+')[0]
}

function Test-LocalServer {
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(400, $false)
        if (-not $ok) { return $false }
        $client.EndConnect($iar) | Out-Null
        return $true
    } catch {
        return $false
    } finally {
        if ($client) { $client.Close() }
    }
}

function Start-LocalServerIfNeeded {
    if (Test-LocalServer) {
        Write-Ok "Local server pehle se chal raha hai: $LocalUrl"
        return
    }
    if (-not (Test-Path (Join-Path $RepoRoot 'db\local.db'))) {
        throw 'db\local.db missing. Pehle run-local.bat (Fast Run) ek dafa chalao.'
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw 'Python PATH mein nahi mila.'
    }

    $starter = Join-Path $PSScriptRoot 'start-local-usb-server.bat'
    Write-Ok "Local server start ho raha hai (nayi window)..."
    Start-Process -FilePath $starter -ArgumentList "$Port" -WorkingDirectory $RepoRoot | Out-Null

    $deadline = (Get-Date).AddSeconds(90)
    do {
        Start-Sleep -Seconds 2
        if (Test-LocalServer) {
            Write-Ok "Server ready: $LocalUrl"
            return
        }
    } while ((Get-Date) -lt $deadline)

    throw "Local server $LocalUrl pe start nahi hua. Dusri window ka error dekho."
}

function Ensure-ProductionBackup {
    $currentUrl = Get-JsonServerUrl $ConfigPath
    if ($currentUrl -like 'https://*onrender.com*') {
        Copy-Item -LiteralPath $ConfigPath -Destination $BakPath -Force
    }
    if (-not (Test-Path $BakPath)) {
        # The repo config was left on a LAN/dev URL (old point-capacitor-to-lan flow)
        # and no backup exists. Rebuild the production backup from known values
        # instead of failing the whole install.
        if ($currentUrl) {
            Write-Warn "capacitor.config.json '$currentUrl' pe hai (LAN/dev). Production backup default URL se banaya."
        }
        $prod = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $prod.server.url = 'https://fleet-management-xdvj.onrender.com'
        $prod.server.startPath = '/mobile-init'
        $prod.server.cleartext = $false
        $prod.server.androidScheme = 'https'
        $prod | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $BakPath -Encoding UTF8
    }
}

function Ensure-DebugCleartextManifest {
    if (Test-Path $DebugManifest) { return }
    $dir = Split-Path $DebugManifest -Parent
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
    }
    @'
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:tools="http://schemas.android.com/tools">
    <application
        android:usesCleartextTraffic="true"
        tools:replace="android:usesCleartextTraffic" />
</manifest>
'@ | Set-Content -LiteralPath $DebugManifest -Encoding UTF8
    Write-Ok 'debug AndroidManifest (cleartext) likh diya.'
}

function Sync-CapacitorIfNeeded {
    $desiredUrl = if ($Mode -eq 'Local') { $LocalUrl.TrimEnd('/') } else { (Get-JsonServerUrl $BakPath).TrimEnd('/') }
    $assetUrl = Get-JsonServerUrl $AssetsConfig
    if ((-not $ForceSync) -and $assetUrl -and ($assetUrl -ieq $desiredUrl)) {
        Write-Ok "Cap sync skip (app pehle se $desiredUrl pe hai)."
        return
    }

    Write-Ok "Cap sync: $assetUrl -> $desiredUrl"
    $npxCmd = (Get-Command npx.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npxCmd) { throw 'npx.cmd nahi mila. Node.js install karo.' }

    $preSync = Join-Path $env:TEMP 'fleet-capacitor-presync.json'
    Copy-Item -LiteralPath $ConfigPath -Destination $preSync -Force
    try {
        if ($Mode -eq 'Local') {
            Copy-Item -LiteralPath $LocalTemplate -Destination $ConfigPath -Force
            if ($Port -ne 5050) {
                $localCfg = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $localCfg.server.url = $LocalUrl
                $localCfg | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
            }
        } else {
            Copy-Item -LiteralPath $BakPath -Destination $ConfigPath -Force
        }
        & $npxCmd cap sync android
        if ($LASTEXITCODE -ne 0) { throw "npx cap sync android failed (exit $LASTEXITCODE)" }
    } finally {
        Copy-Item -LiteralPath $preSync -Destination $ConfigPath -Force
        if (Test-Path $BakPath) {
            Copy-Item -LiteralPath $BakPath -Destination $ConfigPath -Force
        }
    }
    Write-Ok 'Repo capacitor.config.json production URL pe wapas hai (git clean).'
}

function Uninstall-OldApp([string]$Adb, [string]$Serial) {
    $out = & $Adb -s $Serial uninstall $AppId 2>&1 | Out-String
    if ($out -match 'Success') {
        Write-Ok 'Purani Fleet Manager app delete ho gayi.'
    } else {
        Write-Ok 'Phone pe pehle se app nahi thi (ya pehle delete ho chuki).'
    }
}

function Install-DebugApk {
    $gradlew = Join-Path $RepoRoot 'android\gradlew.bat'
    if (-not (Test-Path $gradlew)) { throw 'android\gradlew.bat missing.' }
    Push-Location (Join-Path $RepoRoot 'android')
    try {
        & $gradlew installDebug
        if ($LASTEXITCODE -ne 0) { throw "gradlew installDebug failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
    Write-Ok "Nayi app install: $(Get-AppVersionLabel)"
}

function New-DesktopShortcuts {
    $desktop = [Environment]::GetFolderPath('Desktop')
    if (-not (Test-Path $desktop)) { throw "Desktop folder nahi mila: $desktop" }

    $localBat = Join-Path $RepoRoot 'Install-Local-App.bat'
    $onlineBat = Join-Path $RepoRoot 'Install-Online-App.bat'
    $menuBat = Join-Path $RepoRoot 'Install-Mobile-App.bat'
    $startLocalBat = Join-Path $RepoRoot 'Start-Mobile-Local.bat'
    $wsh = New-Object -ComObject WScript.Shell

    $folders = @(
        $desktop,
        (Join-Path $desktop 'Software Run')
    ) | Where-Object { Test-Path $_ }

    $items = @(
        @{ Name = 'Fleet Local App Install'; Target = $localBat },
        @{ Name = 'Fleet Online App Install'; Target = $onlineBat },
        @{ Name = 'Fleet App Install'; Target = $menuBat },
        @{ Name = 'Fleet Mobile Server Start'; Target = $startLocalBat }
    )
    foreach ($folder in $folders) {
        foreach ($item in $items) {
            $lnk = Join-Path $folder "$($item.Name).lnk"
            $sc = $wsh.CreateShortcut($lnk)
            $sc.TargetPath = $item.Target
            $sc.WorkingDirectory = $RepoRoot
            $sc.WindowStyle = 1
            $sc.Description = $item.Name
            $sc.Save()
            Write-Ok $lnk
        }
    }
}

if ($CreateShortcuts) {
    Write-Host 'Desktop shortcuts bana rahe hain...' -ForegroundColor Cyan
    New-DesktopShortcuts
    if ($Pause) { Write-Host ''; Read-Host 'Enter dabao window band karne ke liye' | Out-Null }
    exit 0
}

$onlineUrl = $null
try {
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Yellow
    if ($Mode -eq 'Local') {
        Write-Host '  LOCAL SERVER APP  ->  phone + laptop Flask' -ForegroundColor Yellow
    } else {
        Write-Host '  ONLINE SERVER APP  ->  phone + Render' -ForegroundColor Yellow
    }
    Write-Host "  Version: $(Get-AppVersionLabel)" -ForegroundColor Yellow
    Write-Host '============================================================' -ForegroundColor Yellow

    Set-AndroidBuildEnv
    $adb = Get-AdbPath
    $serial = Get-PhoneSerial $adb
    Write-Step "Phone: $serial"
    Write-Ok "adb: $adb"

    Ensure-ProductionBackup
    $onlineUrl = Get-JsonServerUrl $BakPath
    Ensure-DebugCleartextManifest

    if ($Mode -eq 'Local') {
        Write-Step 'Local server'
        Start-LocalServerIfNeeded
        Write-Step "USB reverse  tcp:$Port -> laptop:$Port"
        & $adb -s $serial reverse --remove-all 2>$null | Out-Null
        & $adb -s $serial reverse "tcp:$Port" "tcp:$Port"
        if ($LASTEXITCODE -ne 0) { throw 'adb reverse fail. Cable check karo.' }
        Write-Ok "Phone 127.0.0.1:$Port laptop server pe jaayegi"
    }

    Write-Step 'Capacitor config'
    Sync-CapacitorIfNeeded

    Write-Step 'Purani app delete'
    Uninstall-OldApp $adb $serial

    Write-Step 'Nayi app build + install'
    Install-DebugApk

    Write-Step 'App open'
    & $adb -s $serial shell am start -n $LaunchActivity | Out-Null
    Write-Ok 'Phone pe Fleet Manager khul gayi.'

    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Green
    Write-Host '  HO GAYA' -ForegroundColor Green
    if ($Mode -eq 'Local') {
        Write-Host "  Server: $LocalUrl" -ForegroundColor Green
        Write-Host '  Login ke baad GREEN DEV banner hona chahiye.' -ForegroundColor Green
        Write-Host '  USB cable lagi rakho. Local server window band na karo.' -ForegroundColor Green
    } else {
        Write-Host "  Server: $onlineUrl" -ForegroundColor Green
        Write-Host '  Ye Render / online data hai. Green DEV banner nahi hona chahiye.' -ForegroundColor Green
    }
    Write-Host "  App version: $(Get-AppVersionLabel)" -ForegroundColor Green
    Write-Host '  Agli dafa version bump ke baad yahi shortcut chalao.' -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor Green
} catch {
    Write-Host ''
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    if ($Pause) { Write-Host ''; Read-Host 'Enter dabao window band karne ke liye' | Out-Null }
    exit 1
}

if ($Pause) {
    Write-Host ''
    Read-Host 'Enter dabao window band karne ke liye' | Out-Null
}
