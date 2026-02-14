param(
    [switch]$Lan
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$fletPath = Join-Path $PSScriptRoot "venv\Scripts\flet.exe"
if (-not (Test-Path $fletPath)) {
    Write-Host "flet.exe not found in venv\Scripts" -ForegroundColor Red
    exit 1
}

$existing = Get-NetTCPConnection -LocalPort 8550 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $procIds = $existing | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $procIds) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped existing process on 8550: $procId" -ForegroundColor Yellow
    }
    Start-Sleep -Milliseconds 300
}

Write-Host "Starting Flet web mode on http://localhost:8550" -ForegroundColor Cyan
if (Test-Path Env:PORT) { Remove-Item Env:PORT -ErrorAction SilentlyContinue }
if (Test-Path Env:FLET_FORCE_WEB) { Remove-Item Env:FLET_FORCE_WEB -ErrorAction SilentlyContinue }

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

$hostValue = if ($Lan) { "0.0.0.0" } else { "localhost" }
$displayUrl = if ($Lan) { "http://<PC-IP>:8550" } else { "http://localhost:8550" }

Write-Host "Web URL: $displayUrl" -ForegroundColor Green
& $fletPath run main.py --web --port 8550 --host $hostValue --hidden
