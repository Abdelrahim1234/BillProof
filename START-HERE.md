# BillBuster: start here

This file describes the current application. The repository is a monorepo with
two application directories:

```text
frontend/   Next.js patient flow, projector screen, and server-side API proxy
backend/    FastAPI REST API, FastMCP server, seed/admin scripts, and storage
docs/       Product, data, matching, privacy, and implementation contracts
```

For the complete production-mode local experience, run `./demo.sh` from the
repository root and open `http://localhost:3000/present`.

## Current data scope

The active market is `nrv_core_v1` and contains exactly two hospitals:

- LewisGale Hospital Montgomery
- Carilion New River Valley Medical Center

The seed contains 21 verified, non-synthetic price rows from those hospitals'
official machine-readable files. The example patient bill is synthetic and is
labeled that way throughout the flow.

Inova Fairfax and the urgent-care identities may remain in seed or stored data,
but they are outside the active market. Runtime hospital lookup, public price
evidence, analysis, map search, and readiness checks exclude them. Stored rows
also must be non-synthetic and tied to an active source manifest before they can
be returned as public evidence.

## Run the complete app locally

The one-command judge path is:

```bash
./demo.sh
```

For separate development servers, start the backend in one terminal:

```bash
cd backend
cp .env.example .env       # only when .env does not already exist
uv sync --extra dev
uv run python scripts/seed.py
uv run uvicorn billproof.api.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal:

```bash
cd frontend
cp .env.example .env.local # only when .env.local does not already exist
npm ci
npm run dev
```

Open <http://localhost:3000> for the patient flow or
<http://localhost:3000/present> for the projector screen. Browser requests stay
on port 3000; the Next.js server-side proxy forwards `/api/v1/*` to the backend
origin configured by `BACKEND_API_URL`. Case credentials are kept in an
HttpOnly cookie rather than exposed to browser JavaScript.

For a production-mode local frontend build, use `npm run present` instead of
`npm run dev`.

## Verify only the backend

With the backend running:

```bash
curl -s http://127.0.0.1:8000/api/v1/health
curl -s http://127.0.0.1:8000/api/v1/ready
curl -s http://127.0.0.1:8000/api/v1/demo/samples
```

FastAPI serves interactive API documentation at
<http://127.0.0.1:8000/docs> and the generated schema at
<http://127.0.0.1:8000/openapi.json>.

The active-market readiness command checks both hospitals, real source
manifests, non-synthetic evidence, stable citation URLs, the two hero codes,
both analysis scenarios, and case deletion:

```bash
cd backend
uv run python -m scripts.readiness
```

## Tests

```bash
cd backend
uv run pytest -q
uv run ruff check .

cd ../frontend
npm test
npm run typecheck
npm run build
```

## Storage

Local development and tests use `STORAGE_BACKEND=file`, which writes two
gitignored JSON stores under `data/store/`. MongoDB is an explicit
server-side option using the same repositories; setting `MONGODB_URI` alone
does not activate it. See `backend/docs/ATLAS_SETUP.md` for configuration,
index initialization, redacted inventory, and reversible cleanup planning.

Never place `MONGODB_URI` or the backend origin in a `NEXT_PUBLIC_*` variable.

## Documentation map

- `CLAUDE.md` — non-negotiable product and safety invariants
- `docs/01-product-truth.md` — language, labels, safety, and accessibility
- `docs/02-data-contract.md` — enums, models, ingestion, and extraction
- `docs/03-matching-and-scoring.md` — matching tiers and review scoring
- `docs/04-api-and-mcp-contract.md` — intended REST and MCP behavior
- `docs/05-proofmap.md` — facilities, evidence, map, and cost-share behavior
- `docs/99-human-tasks.md` — source verification that requires human review
- `backend/README.md` — backend operation and demo commands
- `backend/docs/API_CONTRACT.md` — routes implemented by the current backend
- `frontend/README.md` — patient flow, projector mode, and frontend settings
