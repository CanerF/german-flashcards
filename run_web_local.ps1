param(
    [switch]$Lan
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$pythonPath = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    Write-Host "python.exe not found in venv\Scripts" -ForegroundColor Red
    exit 1
}

function Test-LocalClientConnected {
    param(
        [int]$Port
    )

    $connections = Get-NetTCPConnection -LocalPort $Port -State Established -ErrorAction SilentlyContinue |
        Where-Object { $_.RemoteAddress -in @("127.0.0.1", "::1") }
    return [bool]$connections
}

$hadOpenBrowserTab = Test-LocalClientConnected -Port 8550

$existing = Get-NetTCPConnection -LocalPort 8550 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $procIds = $existing | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $procIds) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped existing process on 8550: $procId" -ForegroundColor Yellow
    }
    Start-Sleep -Milliseconds 300
}

$stalePython = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -like "*main.py*" -and
        $_.CommandLine -like "*$PSScriptRoot*"
    }
foreach ($proc in $stalePython) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped stale app process: $($proc.ProcessId)" -ForegroundColor Yellow
}

Write-Host "Starting Flet web mode on http://localhost:8550" -ForegroundColor Cyan
$env:PORT = "8550"
$env:FLET_FORCE_WEB = "1"
$env:FLET_WEB_HOST = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }

if (-not $env:FLET_SECRET_KEY -or [string]::IsNullOrWhiteSpace($env:FLET_SECRET_KEY)) {
    $env:FLET_SECRET_KEY = [Guid]::NewGuid().ToString("N")
    Write-Host "Generated temporary FLET_SECRET_KEY for web uploads." -ForegroundColor Yellow
}

$uploadDir = Join-Path $PSScriptRoot ".flet_uploads"
if (-not (Test-Path $uploadDir)) {
    New-Item -ItemType Directory -Path $uploadDir | Out-Null
}
$env:FLET_UPLOAD_DIR = $uploadDir
Write-Host "Upload dir: $uploadDir" -ForegroundColor DarkCyan

$displayUrl = if ($Lan) { "http://<PC-IP>:8550" } else { "http://localhost:8550" }

Write-Host "Web URL: $displayUrl" -ForegroundColor Green
& $pythonPath main.py
