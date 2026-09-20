#!/usr/bin/env sh
# Container entrypoint for hosts that inject $PORT (Railway, Fly, Render, Cloud Run).
# Seeding is upsert-style, so running it on every boot is safe and makes a fresh
# container come up already populated with the verified price rows.
set -e

PORT="${PORT:-8000}"

if [ "${RUN_SEED:-true}" = "true" ]; then
  echo "==> Seeding price data"
  uv run python scripts/seed.py
fi

echo "==> Starting API on 0.0.0.0:${PORT}"
exec uv run uvicorn billproof.api.main:app --host 0.0.0.0 --port "${PORT}"
