# Fast mobile local connect: Flask + adb reverse. No APK rebuild/install.
# USB nikalne ke baad yahi shortcut chalao. Window khuli rakho - cable wapas
# lagte hi reverse automatically lag jata hai.
param(
    [int]$Port = 5050,
    [switch]$Once,
    [switch]$CreateShortcut
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot
$Host.UI.RawUI.WindowTitle = "Fleet Mobile USB Link :$Port"

$AppId = 'com.fleetmanager.app'
$LaunchActivity = 'com.fleetmanager.app/.MainActivity'
$LocalUrl = "http://127.0.0.1:$Port"
$ServerBat = Join-Path $PSScriptRoot 'start-local-usb-server.bat'

function Write-Ok([string]$Message) {
    Write-Host ('    ' + $Message) -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host ('    ' + $Message) -ForegroundColor Yellow
}

function Get-AdbPath {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'),
        $(if ($env:ANDROID_HOME) { Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe' } else { $null }),
        (Join-Path ${env:ProgramFiles} 'Android\Android Studio\platform-tools\adb.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    if (-not $candidates) {
        throw 'adb.exe nahi mila. Android SDK platform-tools install karo.'
    }
    return $candidates[0]
}

function Get-PhoneState([string]$Adb) {
    $rows = @(& $Adb devices 2>$null)
    $ready = @($rows | Where-Object { $_ -match '^\S+\s+device$' })
    $unauthorized = @($rows | Where-Object { $_ -match 'unauthorized' })
    $offline = @($rows | Where-Object { $_ -match '\soffline$' })
    if ($unauthorized) {
        return [pscustomobject]@{ Status = 'unauthorized'; Serial = $null }
    }
    if ($ready) {
        return [pscustomobject]@{ Status = 'ready'; Serial = ($ready[0] -split '\s+')[0] }
    }
    if ($offline) {
        return [pscustomobject]@{ Status = 'offline'; Serial = $null }
    }
    return [pscustomobject]@{ Status = 'missing'; Serial = $null }
}

function Test-PortOpen {
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

function Test-LocalServer {
    return (Test-PortOpen)
}

function Test-PythonAppRunning {
    try {
        $rows = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
        foreach ($row in $rows) {
            if ($row.CommandLine -and ($row.CommandLine -match 'app\.py')) {
                return $true
            }
        }
    } catch {
        return $false
    }
    return $false
}

function Start-LocalServerWindow {
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot 'db\local.db'))) {
        throw 'db\local.db missing. Pehle run-local.bat (Fast Run) ek dafa chalao.'
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw 'Python PATH mein nahi mila.'
    }
    if (-not (Test-Path -LiteralPath $ServerBat)) {
        throw "Missing $ServerBat"
    }

    Start-Process -FilePath $ServerBat -ArgumentList "$Port" -WorkingDirectory $RepoRoot | Out-Null
}

function Wait-LocalServer([int]$Seconds = 90) {
    $started = Get-Date
    $deadline = $started.AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-LocalServer) { return $true }
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        Write-Host ("{0}  Server boot wait... {1}s / {2}s" -f (Get-Date -Format 'HH:mm:ss'), $elapsed, $Seconds) -ForegroundColor Yellow
        Start-Sleep -Seconds 2
    }
    return (Test-LocalServer)
}

function Set-UsbReverse([string]$Adb, [string]$Serial) {
    & $Adb -s $Serial reverse --remove-all 2>$null | Out-Null
    & $Adb -s $Serial reverse "tcp:$Port" "tcp:$Port"
    return ($LASTEXITCODE -eq 0)
}

function Test-AppInstalled([string]$Adb, [string]$Serial) {
    $out = & $Adb -s $Serial shell pm path $AppId 2>$null | Out-String
    return ($out -match 'package:')
}

function New-StartShortcut {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $bat = Join-Path $RepoRoot 'Start-Mobile-Local.bat'
    $targets = @(
        $desktop,
        (Join-Path $desktop 'Software Run')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

    $wsh = New-Object -ComObject WScript.Shell
    foreach ($folder in $targets) {
        $lnk = Join-Path $folder 'Fleet Mobile Server Start.lnk'
        $sc = $wsh.CreateShortcut($lnk)
        $sc.TargetPath = $bat
        $sc.WorkingDirectory = $RepoRoot
        $sc.WindowStyle = 1
        $sc.Description = 'USB disconnect ke baad local mobile server + adb reverse jaldi start'
        $sc.Save()
        Write-Ok $lnk
    }
}

if ($CreateShortcut) {
    Write-Host 'Shortcut bana raha hoon...' -ForegroundColor Cyan
    New-StartShortcut
    exit 0
}

Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host '  FLEET MOBILE USB LINK  (install nahi, sirf server)' -ForegroundColor Green
Write-Host ('  Server: ' + $LocalUrl) -ForegroundColor Green
Write-Host '  USB nikalne ke baad cable wapas lagao - ye window khuli rakho.' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''

$adb = Get-AdbPath
Write-Ok ('adb: ' + $adb)

$script:LaunchedServer = $false
$lastSerial = $null
$reverseOk = $false
$appOpened = $false
$lastNote = ''

while ($true) {
    if (-not (Test-LocalServer)) {
        $already = Test-PythonAppRunning
        if (-not $already -and -not $script:LaunchedServer) {
            Write-Host ('{0}  Local server window start ho rahi hai...' -f (Get-Date -Format 'HH:mm:ss')) -ForegroundColor Yellow
            Start-LocalServerWindow
            $script:LaunchedServer = $true
        } elseif ($already) {
            Write-Host ('{0}  Python pehle se chal raha hai, port wait...' -f (Get-Date -Format 'HH:mm:ss')) -ForegroundColor Yellow
        }

        $ready = Wait-LocalServer 90
        if (-not $ready) {
            Write-Host ('{0}  Server {1} pe ready nahi. Dusri window "Fleet Local Server" dekho.' -f (Get-Date -Format 'HH:mm:ss'), $LocalUrl) -ForegroundColor Red
            $script:LaunchedServer = $false
            if ($Once) { exit 1 }
            Start-Sleep -Seconds 4
            continue
        }
        Write-Host ('{0}  Server ready: {1}' -f (Get-Date -Format 'HH:mm:ss'), $LocalUrl) -ForegroundColor Green
        $lastNote = 'server-ready'
    }

    $phone = Get-PhoneState $adb
    if ($phone.Status -eq 'unauthorized') {
        $reverseOk = $false
        $note = 'Phone pe USB debugging Allow dabao.'
        if ($note -ne $lastNote) {
            Write-Host ('{0}  {1}' -f (Get-Date -Format 'HH:mm:ss'), $note) -ForegroundColor Yellow
            $lastNote = $note
        }
        if ($Once) { throw $note }
        Start-Sleep -Seconds 2
        continue
    }

    if ($phone.Status -ne 'ready') {
        $reverseOk = $false
        $lastSerial = $null
        $appOpened = $false
        $note = 'Phone USB wait... cable lagao, File Transfer + USB debugging ON.'
        if ($note -ne $lastNote) {
            Write-Host ('{0}  {1}' -f (Get-Date -Format 'HH:mm:ss'), $note) -ForegroundColor Yellow
            $lastNote = $note
        }
        if ($Once) { throw 'Koi phone connected nahi.' }
        Start-Sleep -Seconds 2
        continue
    }

    $needReverse = (-not $reverseOk) -or ($lastSerial -ne $phone.Serial)
    if ($needReverse) {
        if (Set-UsbReverse $adb $phone.Serial) {
            $reverseOk = $true
            $lastSerial = $phone.Serial
            Write-Host ('{0}  USB reverse OK  ({1}  tcp:{2})' -f (Get-Date -Format 'HH:mm:ss'), $phone.Serial, $Port) -ForegroundColor Green
            $lastNote = 'reverse-ok'
        } else {
            $reverseOk = $false
            Write-Host ('{0}  adb reverse fail. Cable check karo.' -f (Get-Date -Format 'HH:mm:ss')) -ForegroundColor Red
            $lastNote = 'reverse-fail'
            if ($Once) { throw 'adb reverse fail.' }
            Start-Sleep -Seconds 2
            continue
        }
    }

    if (-not $appOpened) {
        if (Test-AppInstalled $adb $phone.Serial) {
            & $adb -s $phone.Serial shell am start -n $LaunchActivity 2>$null | Out-Null
            Write-Host ('{0}  Fleet Manager phone pe open ho gayi.' -f (Get-Date -Format 'HH:mm:ss')) -ForegroundColor Green
        } else {
            Write-Warn 'Phone pe app nahi mili. Pehle Fleet Local App Install chalao.'
        }
        $appOpened = $true
        $lastNote = 'app-open'
    }

    if ($Once) {
        Write-Host ''
        Write-Host '  Server + USB link ready. Window band kar sakte ho.' -ForegroundColor Green
        exit 0
    }

    Start-Sleep -Seconds 2
}
