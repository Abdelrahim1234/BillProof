#!/usr/bin/env sh
set -eu

# Container entrypoint for hosts that inject PORT. Seeding is idempotent, so a
# fresh preview comes up with the small verified demo extract already loaded.
PORT="${PORT:-8000}"

if [ "${RUN_SEED:-true}" = "true" ]; then
  echo "==> Seeding BillBuster reference data"
  uv run python scripts/seed.py
fi

echo "==> Starting BillBuster API on 0.0.0.0:${PORT}"
exec uv run uvicorn billproof.api.main:app --host 0.0.0.0 --port "${PORT}"
