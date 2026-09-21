# Wait until the local Flask server answers, then open the browser.
# Launched hidden from run-local.bat so no extra PowerShell window stays open.
param(
    [int]$Port = 5050
)

$ErrorActionPreference = 'SilentlyContinue'
$url = "http://127.0.0.1:$Port/"

for ($i = 0; $i -lt 60; $i++) {
    & curl.exe -s -o NUL --max-time 3 -f $url
    if ($LASTEXITCODE -eq 0) {
        Start-Process $url
        exit 0
    }
    Start-Sleep -Seconds 1
}

Start-Process $url
exit 0
