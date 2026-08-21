# One-command demo launch: FastAPI backend + Next.js dashboard, both
# reading only from data/snapshots/ -- uv + npm is the whole toolchain
# for this script, no network calls except the Analyst panel. A Docker
# path also exists (docker-compose.yml, `docker compose up --build`) for
# anyone who'd rather not install uv/npm locally -- see README.md.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "created .env from .env.example (no keys needed for the dashboard)"
}

Write-Host "Starting Project Sentinel API on :8000..."
$api = Start-Process -PassThru -NoNewWindow uv "run python api/main.py"

Write-Host "Starting the dashboard on :3000..."
$web = Start-Process -PassThru -NoNewWindow npm "--prefix web run dev"

Start-Sleep -Seconds 4
Start-Process "http://localhost:3000"

Write-Host "Ready: http://localhost:3000  (Ctrl+C stops both processes)"
try {
    Wait-Process -Id $api.Id, $web.Id
} finally {
    Stop-Process -Id $api.Id, $web.Id -Force -ErrorAction SilentlyContinue
}
