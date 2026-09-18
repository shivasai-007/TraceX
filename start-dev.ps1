# Starts the backend and frontend together for local development (Windows).
# Usage:  .\start-dev.ps1
# If PowerShell blocks this, run first:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not (Test-Path "$root\backend\.venv")) {
    Write-Host "No virtualenv found at backend\.venv" -ForegroundColor Yellow
    Write-Host "Run the setup in IMPLEMENTATION.md section 1 first."
    exit 1
}

if (-not (Test-Path "$root\backend\.env")) {
    Write-Host "No backend\.env found. Copying from .env.example -- edit it before tracing." -ForegroundColor Yellow
    Copy-Item "$root\backend\.env.example" "$root\backend\.env"
}

Write-Host "Starting API on http://localhost:8000" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$root\backend'; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port 8000"
)

Start-Sleep -Seconds 2

Write-Host "Starting frontend on http://localhost:5173" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "cd '$root\frontend'; npm run dev"
)

Write-Host ""
Write-Host "Both services are starting in separate windows." -ForegroundColor Green
Write-Host "Open http://localhost:5173 once the frontend finishes building."
