# Deploy ufone-bridge package to WebSouls PK VPS (185.228.92.23)
param(
    [string]$HostName = '185.228.92.23',
    [string]$User = 'root',
    [string]$RemoteDir = '/opt/ufone-bridge',
    [string]$KeyPath = '',
    [string]$PasswordFile = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $KeyPath) { $KeyPath = Join-Path $Root 'deploy_key' }
if (-not $PasswordFile) { $PasswordFile = Join-Path $Root '.vps_password' }

$Pub = Get-Content (Join-Path $Root 'deploy_key.pub') -Raw
Write-Host "Public key (add in WebSouls → SSH Keys if needed):"
Write-Host $Pub

$sshBase = @('-o', 'StrictHostKeyChecking=accept-new', '-o', 'ConnectTimeout=15')
$useKey = Test-Path $KeyPath
$usePass = Test-Path $PasswordFile

function Invoke-Remote([string]$Cmd) {
    if ($useKey) {
        & ssh @sshBase -i $KeyPath "${User}@${HostName}" $Cmd
        if ($LASTEXITCODE -ne 0) { throw "ssh failed: $Cmd" }
        return
    }
    if ($usePass) {
        $pass = (Get-Content $PasswordFile -Raw).Trim()
        if (-not (Get-Command sshpass -ErrorAction SilentlyContinue)) {
            # Windows: use plink if available, else fail with instructions
            if (Get-Command plink -ErrorAction SilentlyContinue) {
                echo y | & plink -ssh -pw $pass "${User}@${HostName}" $Cmd
                if ($LASTEXITCODE -ne 0) { throw "plink failed: $Cmd" }
                return
            }
            throw "Need ssh key auth or sshpass/plink for password. Add deploy_key.pub in WebSouls SSH Keys."
        }
        $env:SSHPASS = $pass
        & sshpass -e ssh @sshBase "${User}@${HostName}" $Cmd
        if ($LASTEXITCODE -ne 0) { throw "sshpass failed: $Cmd" }
        return
    }
    throw "No SSH auth. Create tools/ufone_bridge/.vps_password OR install deploy_key.pub on the VPS."
}

function Copy-ToRemote([string]$Local, [string]$Remote) {
    if ($useKey) {
        & scp @sshBase -i $KeyPath $Local "${User}@${HostName}:${Remote}"
        if ($LASTEXITCODE -ne 0) { throw "scp failed: $Local" }
        return
    }
    if ($usePass -and (Get-Command pscp -ErrorAction SilentlyContinue)) {
        $pass = (Get-Content $PasswordFile -Raw).Trim()
        & pscp -pw $pass $Local "${User}@${HostName}:${Remote}"
        if ($LASTEXITCODE -ne 0) { throw "pscp failed: $Local" }
        return
    }
    throw "Cannot copy without key (scp -i) or pscp+password."
}

Write-Host "Testing SSH to ${User}@${HostName} ..."
try {
    Invoke-Remote 'uname -a && echo SSH_OK'
} catch {
    Write-Host ""
    Write-Host "SSH blocked. Do ONE of:"
    Write-Host "  A) WebSouls → Manage Product → SSH Keys → paste:"
    Write-Host "     $Pub"
    Write-Host "  B) Save root password to: $PasswordFile"
    Write-Host ""
    throw
}

Write-Host "Proving Ufone TLS from VPS..."
Invoke-Remote 'curl -sS -o /dev/null -w "HTTP %{http_code}\n" --connect-timeout 15 --max-time 40 -I https://bpocops.ufone.com/Login.aspx'

Write-Host "Uploading bridge package..."
Invoke-Remote "mkdir -p $RemoteDir/systemd $RemoteDir/sessions"
$files = @(
    'worker.py',
    'worker_pg.py',
    'detail_ops.py',
    'ufone_api_client.py',
    'ufone_creds.py',
    'requirements.txt',
    'bootstrap.sh',
    '.env.example',
    'README.md'
)
foreach ($f in $files) {
    Copy-ToRemote (Join-Path $Root $f) "$RemoteDir/$f"
}
Copy-ToRemote (Join-Path $Root 'systemd\ufone-bridge.service') "$RemoteDir/systemd/ufone-bridge.service"

$localEnv = Join-Path $Root '.env'
if (Test-Path $localEnv) {
    Copy-ToRemote $localEnv "$RemoteDir/.env"
} else {
    Write-Host "WARN: tools/ufone_bridge/.env missing — create from .env.example before bootstrap"
}

Write-Host "Running remote bootstrap..."
Invoke-Remote "chmod +x $RemoteDir/bootstrap.sh && bash $RemoteDir/bootstrap.sh"
Write-Host "Deploy complete."
