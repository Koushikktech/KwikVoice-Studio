#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -x backend/.venv/bin/uvicorn || ! -x frontend/node_modules/.bin/next ]]; then
  printf 'Install dependencies first with uv sync --project backend --python 3.11 and npm ci --prefix frontend.\n' >&2
  exit 1
fi

(
  cd backend
  exec .venv/bin/uvicorn chaoslab.main:app --host 127.0.0.1 --port 8000
) &
backend_pid=$!

(
  cd frontend
  exec node_modules/.bin/next dev --hostname 127.0.0.1 --port 3000
) &
frontend_pid=$!

cleanup() {
  kill "$backend_pid" "$frontend_pid" 2>/dev/null || true
  wait "$backend_pid" "$frontend_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf 'Open http://127.0.0.1:3000\n'
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done
if kill -0 "$backend_pid" 2>/dev/null; then
  wait "$frontend_pid"
else
  wait "$backend_pid"
fi
