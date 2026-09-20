#!/usr/bin/env bash
set -euo pipefail

DEMO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    kill "${FRONTEND_PID}" 2>/dev/null || true
    wait "${FRONTEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

for command_name in uv npm curl; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
done

echo "Preparing the locked backend environment..."
(
  cd "${DEMO_ROOT}/backend"
  uv sync --extra dev --frozen
  STORAGE_BACKEND=file uv run python scripts/seed.py
)

if [[ ! -d "${DEMO_ROOT}/frontend/node_modules" ]]; then
  echo "Installing locked frontend dependencies..."
  (cd "${DEMO_ROOT}/frontend" && npm ci)
fi

echo "Starting BillBuster API on http://127.0.0.1:${BACKEND_PORT} ..."
(
  cd "${DEMO_ROOT}/backend"
  STORAGE_BACKEND=file uv run uvicorn billproof.api.main:app --host 127.0.0.1 --port "${BACKEND_PORT}"
) &
BACKEND_PID=$!

for attempt in {1..40}; do
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/v1/ready" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "The backend stopped before it became ready." >&2
    exit 1
  fi
  if [[ "${attempt}" -eq 40 ]]; then
    echo "The backend did not become ready within 20 seconds." >&2
    exit 1
  fi
  sleep 0.5
done

echo
echo "Building the production frontend..."
(cd "${DEMO_ROOT}/frontend" && BACKEND_API_URL="http://127.0.0.1:${BACKEND_PORT}" npm run build)

echo
echo "BillBuster is ready. Open http://localhost:${FRONTEND_PORT}/present"
echo "Press Ctrl+C to stop both services."
echo

cd "${DEMO_ROOT}/frontend"
BACKEND_API_URL="http://127.0.0.1:${BACKEND_PORT}" \
  npx next start -H 0.0.0.0 -p "${FRONTEND_PORT}" &
FRONTEND_PID=$!
wait "${FRONTEND_PID}"
