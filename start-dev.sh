#!/usr/bin/env bash
# Starts the backend and frontend together for local development (Linux/macOS).
# Windows: use start-dev.ps1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$ROOT/backend/.venv" ]; then
  echo "No virtualenv found at backend/.venv"
  echo "Run the setup in IMPLEMENTATION.md section 1 first."
  exit 1
fi

if [ ! -f "$ROOT/backend/.env" ]; then
  echo "No backend/.env found. Copying from .env.example -- edit it before tracing."
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
fi

cleanup() { echo; echo "Stopping..."; kill 0; }
trap cleanup EXIT INT TERM

echo "Starting API on http://localhost:8000"
(
  cd "$ROOT/backend"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  uvicorn app.main:app --reload --port 8000
) &

sleep 2

echo "Starting frontend on http://localhost:5173"
(
  cd "$ROOT/frontend"
  npm run dev
) &

wait
