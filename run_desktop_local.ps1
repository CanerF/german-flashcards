$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$pythonPath = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    Write-Host "python.exe not found in venv\Scripts" -ForegroundColor Red
    exit 1
}

if (Test-Path Env:PORT) {
    Remove-Item Env:PORT
    Write-Host "Cleared PORT environment variable for desktop mode." -ForegroundColor Yellow
}

if (Test-Path Env:FLET_FORCE_WEB) {
    Remove-Item Env:FLET_FORCE_WEB
}

Write-Host "Starting desktop mode..." -ForegroundColor Cyan
& $pythonPath main.py
