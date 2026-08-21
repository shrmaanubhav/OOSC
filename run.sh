#!/usr/bin/env bash
# One-command demo launch: FastAPI backend + Next.js dashboard, both
# reading only from data/snapshots/ -- uv + npm is the whole toolchain
# for this script, no network calls except the Analyst panel. A Docker
# path also exists (docker-compose.yml, `docker compose up --build`) for
# anyone who'd rather not install uv/npm locally -- see README.md.
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "created .env from .env.example (no keys needed for the dashboard)"
fi

echo "Starting Project Sentinel API on :8000..."
uv run python api/main.py &
API_PID=$!

echo "Starting the dashboard on :3000..."
npm --prefix web run dev &
WEB_PID=$!

trap "kill $API_PID $WEB_PID 2>/dev/null" EXIT INT TERM

sleep 3
( sleep 4; open http://localhost:3000 2>/dev/null || xdg-open http://localhost:3000 2>/dev/null || true ) &

echo "Ready: http://localhost:3000  (Ctrl+C stops both processes)"
wait
