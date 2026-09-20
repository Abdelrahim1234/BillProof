# Demo runbook

Every command below was run against this repository during the Mongo
migration and works fully offline -- no network access, no real Atlas
cluster, no system packages beyond what `uv sync` installs.

## 1. Install dependencies

```bash
cd backend
cp .env.example .env
uv sync --extra dev
```

`.env` selects `STORAGE_BACKEND=file` by default, so an unrelated URI in the
process environment cannot redirect the demo. The local files live under
the workspace-level `../data/store/` and are gitignored.

## 2. (Optional) local OCR

Not required -- no OCR provider is wired up in this pass
(`EXTRACTION_SCHEMA.md`). Skip this step; `OCR_PROVIDER=local` in `.env` is
inert today.

## 3. Initialize the offline database and seed data

```bash
uv run python scripts/seed.py
```

Expected output:

```
Seeded facilities and 8 service bundles.
Loaded 21 verified price rows from 2 official MRFs.
Synthetic price rows in database: 0.
```

This writes to `../data/store/billproof_public.json`
(`Facility`, `PriceRecord`, `FacilitySource`, `ServiceBundle` documents) --
gitignored, safe to delete and re-run at any time.

## 4. (Optional) initialize Atlas indexes

Only if you've completed `ATLAS_SETUP.md` and explicitly selected the MongoDB
backend (including its remote-target opt-in) in `.env`:

```bash
uv run python -c "
import asyncio
from billproof import store
async def main():
    await store.connect()
    print(store.backend_name(), await store.init_indexes())
    await store.close()
asyncio.run(main())
"
```

## 5. Start the backend

```bash
uv run uvicorn billproof.api.main:app --reload
```

Verify:

```bash
curl http://127.0.0.1:8000/api/v1/ready
# {"data":{"status":"ok","db":"ok","seeded":true}, ...}
```

## 6. Start the MCP server (separate process)

```bash
uv run mcp dev src/billproof/mcp_server.py
```

It shares the same selected storage backend as the API process (both read the
`STORAGE_BACKEND` and corresponding database settings from `.env`), so data
seeded in step 3 is visible to MCP tools immediately.

## 7. Active-market data boundary

The judge build intentionally uses LewisGale Montgomery and Carilion NRV only.
Inova is retained as an out-of-market facility for future research, but its rows
are not loaded into the runtime price seed and cannot be returned as evidence.
Do not expand the market immediately before judging.

The checked-in 21-row extract is sufficient for the offline demo. The original
326 MB and 56 MB hospital MRFs are deliberately not committed. To validate the
ingestion path without downloading either source, run the importer against its
small local parser fixture:

```bash
uv run python scripts/ingest_mrf.py \
  --file data/fixtures/cms_v3_small.json \
  --hospital-name "LewisGale Hospital Montgomery" \
  --source-type cms_mrf --synthetic \
  --source-url https://example.invalid/cms-hpt.json \
  --dry-run
# Validated N price rows from data/fixtures/cms_v3_small.json for LewisGale Hospital Montgomery.
```

Keep `--dry-run` for synthetic parser fixtures. Raw CMS tall and wide CSV files
can be reduced with `convert_tall_cms_csv.py` and `convert_wide_cms_csv.py`, but
any replacement seed still needs human verification, provenance, and a passing
`scripts.readiness` run.

## 8. Synthetic end-to-end walkthrough

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/demo/cases \
  -H "Content-Type: application/json" \
  -d '{"sample":"nrv_cash_review"}' | python3 -m json.tool
# copy "access_token" and "case_id" from the response

TOKEN=...
CASE=...
curl -s -X POST "http://127.0.0.1:8000/api/v1/cases/$CASE/analysis" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

curl -s -X POST "http://127.0.0.1:8000/api/v1/cases/$CASE/packet" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"goal": "billing_review", "language": "en"}' | python3 -m json.tool
```

## 9. Cleanup / case deletion

```bash
curl -s -X DELETE "http://127.0.0.1:8000/api/v1/cases/$CASE" \
  -H "Authorization: Bearer $TOKEN" -w '%{http_code}\n'
# 204

uv run python scripts/purge_expired_cases.py   # sweeps anything past its TTL
```

To fully reset the offline demo state, stop the services and remove the two
generated JSON stores at `../data/store/`, then reseed. They are gitignored and
contain no source fixtures.

```bash
mv ../data/store ../data/store.pre-demo
uv run python scripts/seed.py
```

Remove the backup only after the fresh demo has been verified.

## 10. Tests and lint

```bash
uv run pytest -q        # 119 passed, fully offline, never touches Atlas
uv run ruff check .     # clean
```
