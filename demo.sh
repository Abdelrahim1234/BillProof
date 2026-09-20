#!/usr/bin/env bash
# Starts the BillProof backend and frontend together for a demo, then prints the
# address to open on the projector. Ctrl-C stops both.
#
#   ./demo.sh                      # LAN: the QR code targets this laptop's Wi-Fi IP
#   PUBLIC_URL=https://x ./demo.sh # tunnel: the QR code targets that URL instead
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_port="${BACKEND_PORT:-8000}"
frontend_port="${FRONTEND_PORT:-3000}"

cleanup() {
  trap - INT TERM EXIT
  [[ -n "${backend_pid:-}" ]] && kill "$backend_pid" 2>/dev/null || true
  [[ -n "${frontend_pid:-}" ]] && kill "$frontend_pid" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

cd "$root/backend"
[[ -f .env ]] || cp .env.example .env
echo "==> Installing backend dependencies"
uv sync --extra dev --quiet
echo "==> Seeding price data"
uv run python scripts/seed.py
echo "==> Starting backend on 127.0.0.1:$backend_port"
uv run uvicorn billproof.api.main:app --host 127.0.0.1 --port "$backend_port" &
backend_pid=$!

cd "$root/frontend"
if [[ ! -d node_modules ]]; then
  echo "==> Installing frontend dependencies"
  npm install --no-audit --no-fund
fi
echo "==> Building frontend"
BACKEND_URL="http://127.0.0.1:$backend_port" npm run build
echo "==> Starting frontend on 0.0.0.0:$frontend_port"
BACKEND_URL="http://127.0.0.1:$backend_port" npx next start -H 0.0.0.0 -p "$frontend_port" &
frontend_pid=$!

cat <<EOF

  Projector screen:  http://localhost:$frontend_port/present
  Phone flow:        http://localhost:$frontend_port/

  The projector page shows the QR code and the address phones should use.
  Press Ctrl-C to stop both servers.

EOF

wait
