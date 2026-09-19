# BillProof backend

Turns a hospital bill into a citation-backed comparison against the
hospital's own publicly disclosed prices, plus a negotiation packet (phone
script, written request, evidence table, assistance path). See
`../CLAUDE.md` and `../docs/` for the full product/data/matching/API
contracts this implementation follows.

The normal seed contains **21 verified, non-synthetic price rows** extracted
from the official LewisGale Montgomery and Carilion NRV machine-readable files.
Original-file hashes, retrieval times, and exact row locators are checked in;
the 326 MB and 56 MB source files are not. The patient statement remains
visibly synthetic.

## Setup

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run python scripts/seed.py
uv run uvicorn billproof.api.main:app --reload
```

The API is now at `http://127.0.0.1:8000`. Interactive OpenAPI docs at
`/docs`; the raw schema is served at `/openapi.json` (no static export
needed -- FastAPI generates it live from the route/schema definitions).

## Tests and lint

```bash
uv run pytest -q          # 60 tests: unit + integration + MCP protocol tests
uv run ruff check .        # clean
```

## MCP server

```bash
uv run mcp dev src/billproof/mcp_server.py   # MCP Inspector, stdio transport
```

The installed SDK is `mcp==1.30.0`. Its real high-level entry point is
`from mcp.server.fastmcp import FastMCP` -- **not** `from mcp.server import
MCPServer`, which does not exist in this version (see `mcp_server.py`'s
module docstring and `CLAUDE.md`'s caution note). `mcp_server.py` can also be
imported directly and driven over `mcp.shared.memory` for in-process testing
(see `tests/integration/test_mcp_server.py`).

## Docker

```bash
docker compose up --build                 # API + seed, SQLite volume
docker compose --profile postgres up --build   # also starts Postgres
```

To point the API at the Postgres service, set `DATABASE_URL` before
bringing the stack up:

```bash
DATABASE_URL=postgresql+psycopg://billproof:billproof@db:5432/billproof \
  docker compose --profile postgres up --build
```

Nothing else changes -- SQLite and Postgres share the same models and
migrations-free `create_all` bootstrap.

## Five-step judge demo

```bash
# 1. Start the API (see Setup above), then create the offline demo case --
#    no network access required.
curl -s -X POST http://127.0.0.1:8000/api/v1/demo/cases | tee /tmp/demo.json

# 2. Pull the token out of the response.
TOKEN=$(jq -r .data.access_token /tmp/demo.json)
CASE_ID=$(jq -r .data.case_id /tmp/demo.json)

# 3. Run the deterministic analysis: one exact/scored match, one contextual
#    (no-allowed-amount) result, one insufficient_data result.
curl -s -X POST http://127.0.0.1:8000/api/v1/cases/$CASE_ID/analysis \
  -H "Authorization: Bearer $TOKEN" | jq .data.status

# 4. Build an English negotiation packet from that analysis.
curl -s -X POST http://127.0.0.1:8000/api/v1/cases/$CASE_ID/packet \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"goal": "billing_review", "language": "en"}' | jq -r .data.markdown

# 5. Show the safe activity receipts (what the system actually did, no
#    chain-of-thought or raw text).
curl -s http://127.0.0.1:8000/api/v1/cases/$CASE_ID/activity \
  -H "Authorization: Bearer $TOKEN" | jq .data
```

## More curl examples

```bash
# Search seeded hospitals
curl -s "http://127.0.0.1:8000/api/v1/hospitals?city=Blacksburg" | jq .

# Nearby facilities (ProofMap), 25-mile radius around Blacksburg
curl -s "http://127.0.0.1:8000/api/v1/map/search?lat=37.2001&lng=-80.4181&radius_miles=25" | jq .

# Out-of-pocket estimate, no member ID ever requested
curl -s -X POST http://127.0.0.1:8000/api/v1/estimates/out-of-pocket \
  -H "Content-Type: application/json" \
  -d '{"allowed_amount": "200.00", "copay": "30.00", "coinsurance_rate": "0.20", "copay_interaction": "in_addition", "remaining_oop_max": "1000.00"}' | jq .
```

## Repository layout

```text
backend/
├── pyproject.toml, .env.example, Dockerfile, docker-compose.yml
├── data/seed/        facility identity, verified price extract + provenance, service bundles
├── data/fixtures/    parser-only synthetic MRF fixtures, demo bill (txt/pdf) + expected outcomes
├── scripts/          seed.py, ingest_mrf.py, purge_expired_cases.py (all admin CLI -- never called from a request)
├── src/billproof/
│   ├── config.py, db.py, models.py, enums.py, errors.py, logging_config.py
│   ├── api/          FastAPI app, routes, case-token dependency
│   ├── schemas/       Pydantic request/response models
│   ├── repositories/  read/write queries, no business logic
│   ├── services/       code_normalizer, price_matching, benchmarking, analysis,
│   │                    packet_builder, case_auth, case_lifecycle, activity, privacy, geo, map_search
│   ├── templates/      Jinja2 negotiation packets (en/es)
│   └── mcp_server.py   FastMCP server -- imports the same services as the REST routes
└── tests/unit/, tests/integration/
```

## What's synthetic vs. real

- The 21 hospital `price_records` rows are verified MRF extracts and have
  `is_synthetic=false`. `data/seed/provenance.json` records the official
  discovery/page/file URLs, schema versions, dates, sizes, and SHA-256 hashes;
  every CSV row has an exact JSON pointer or physical CSV row locator.
- The HCA file jointly lists LewisGale Hospital Montgomery and Christiansburg
  FSER. Its selected imaging/lab rows have no per-location discriminator.
  Neither hospital source states billing class or service units for these rows,
  so those fields are honestly stored as `unknown` and surfaced as limitations.
- The demo patient statement is synthetic and visibly labeled. Its CPT 71046
  comparison uses the real LewisGale Cigna/NPR disclosed rate of $206.54.
- The three urgent-care locations remain unverified placeholders and have no
  seeded price rows; fake `example.invalid` prices were removed.
- One urgent-care location (`Family Urgent Care of Montgomery County`) is
  seeded with **no** price data on purpose, to exercise the honest
  `unavailable` evidence state end-to-end.

## Known P0 gaps (not blocking, see PROGRESS.md's final report)

- Line-total reconciliation ("declared total doesn't match sum of lines")
  is not implemented -- the data contract has no field for a declared total
  to reconcile against.
- `regional_benchmarks` and `plan_benefit_profiles` tables exist and are
  queried by the API/MCP tools but have no seed rows (no compatible
  public aggregate was available to ingest in this environment).
- `GET /cases/{id}/packet/latest.pdf` returns a clean `501` (P1 per docs/04).
- The optional Anthropic PDF-extraction and Turquoise adapters (Stage 10)
  are not implemented; P0 does not require them and the demo works fully
  offline without them.
