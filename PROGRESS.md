# BillProof backend — build progress

Stages per BUILD_BACKEND.md. Update after every stage.

| Stage | Status |
|---|---|
| 1 — Skeleton | green |
| 2 — Models and schemas | green |
| 3 — Seed and ingestion | green |
| 4 — Domain services | green (21 unit/integration tests) |
| 5 — Cases and bills | green (31 tests total) |
| 6 — Analysis, receipts, packets | green (37 tests total) |
| 7 — MCP server | green (43 tests total; mcp==1.30.0, `from mcp.server.fastmcp import FastMCP`) |
| 8 — ProofMap | green (60 tests total after verified-data and migration coverage) |
| 9 — Harden and document | green (Docker/README verified against a live server; `docker build` itself untested, no Docker daemon in this sandbox) |
| 10 — Optional adapters | skipped -- every P0 acceptance criterion above is green; see final report |

## Notes

- `data/seed/public_prices.csv` now contains 21 verified rows from two official
  hospital MRFs. The full source files remain outside the repo; original-file
  hashes, retrieval metadata, and source limitations are in
  `data/seed/provenance.json`.
- Repo has no `.git` — not initializing one, not requested.

---

## Final report (Stages 1-9 complete, Stage 10 skipped)

### What was completed per stage

1. **Skeleton** — `pyproject.toml` (pinned stack), `.env.example`, config,
   SQLAlchemy session, error envelope + request-id middleware, `/health`,
   `/ready`. `uv sync --extra dev` and `uv run pytest -q` green on an empty
   suite, then grown to 60 tests across the build.
2. **Models and schemas** — all tables from docs/02 plus every ProofMap
   table from docs/05 (`service_bundles`, `regional_benchmarks`,
   `plan_benefit_profiles`, `case_evidence`, `facility_assistance`), built in
   this stage so there was never a second migration. Money as
   `Numeric(12,2)`/`Decimal` internally, integer cents (`Money` schema) at
   the API boundary. Enums exactly as specified in docs/02.
3. **Seed and ingestion** — `scripts/seed.py`, `scripts/ingest_mrf.py`
   (streaming `ijson` for the CMS V3 JSON shape, plus a tall-CSV path),
   `scripts/purge_expired_cases.py`, a source-provenance log with SHA-256
   hashes written per ingest run. The normal seed now loads a 21-row verified
   extract from the current LewisGale Montgomery and Carilion NRV MRFs, records
   original-file provenance, removes legacy synthetic seed rows, and is
   idempotent. Synthetic MRFs remain parser-only fixtures and never enter the
   demo database.
4. **Domain services** — `code_normalizer`, `price_matching` (4 automatic
   tiers + tier-5 description-only exclusion), `benchmarking` (peer
   per-hospital representative value before cross-hospital median, freshness
   multiplier, confidence mapping), `analysis` (subject selection per
   coverage type, review-score formula, non-price findings). 21 unit tests
   cover essentially all of docs/03's unit-test list (five-digit ambiguity,
   modifier separation, revenue leading-zero, cross-code-type exclusion,
   cash-price selection, gross-never-preferred, no-invented-midpoint,
   patient-responsibility-never-vs-negotiated-rate, facility/professional
   never mixing, per-unit scaling, peer-median-per-hospital-first, locale
   invariance, protected-trait schema rejection).
5. **Cases and bills** — case token auth (32 random bytes via
   `secrets.token_urlsafe`, SHA-256 hash storage, `hmac.compare_digest`,
   `401` missing / `403` invalid), manual entry, local PDF/text extraction
   (magic-byte sniffing, PII masking before parsing, no OCR provider so
   images get a clean `needs_manual_entry`), bulk-confirm, and
   `POST /api/v1/demo/cases`. The demo endpoint was verified offline (a test
   monkeypatches `socket.socket` to raise, and a live curl run confirmed the
   full five-step flow).
6. **Analysis, receipts, packets** — synchronous analysis endpoint, safe
   `activity_receipts` (transport-tagged), deterministic Jinja2 packets in
   English and Spanish sharing one Python-built content dict so the only
   per-language surface is the template + a static copy table, never a model
   call. A test asserts none of "illegal", "guaranteed savings", "fraud", or
   "you broke the law" ever appears in rendered output.
7. **MCP server** — `mcp_server.py` using `FastMCP`. All seven core tools,
   the `methodology://pricing-comparison` resource, and the
   `prepare_hospital_call` prompt. Protocol-level tests use
   `mcp.shared.memory.create_connected_server_and_client_session` to do a
   real initialize handshake, `list_tools`, and `call_tool` against the
   actual server object — not a mock. `compare_bill_line` is proven
   byte-identical to the REST analysis path for the same inputs (the test
   builds an equivalent REST case and diffs the JSON, excluding only the
   randomly generated `line_id`).
8. **ProofMap** — Haversine radius search (`services/geo.py`, unit-tested
   against the well-known JFK→LAX great-circle distance), facility
   price-evidence, area benchmarks, the exact out-of-pocket formula from
   docs/05 (including the out-of-network never-capped-at-allowed-amount
   rule), case-evidence add/remove with packet invalidation, and all six
   ProofMap MCP tools. Three urgent-care locations were seeded (unverified
   placeholders — see docs/99), one **deliberately with no price data** to
   exercise the honest `unavailable` state end-to-end.
9. **Harden and document** — `Dockerfile` + `docker-compose.yml` (API
   service + optional `postgres` profile), `README.md` with the exact
   start/test commands and a five-step judge demo. Every command in the
   README (`uv sync`, seed, run, the five curl steps, the extra curl
   examples) was actually executed against a live local server as part of
   this stage, not just written. `uv run ruff check .` is clean. OpenAPI is
   served live at `/openapi.json` (25 routes) — no static export needed.

### Test results

`uv run pytest -q` → **60 passed**, 0 failed, 0 skipped.
`uv run ruff check .` → **clean** (after 3 deliberate rule ignores, see
below).

### Every place the implementation differs from the docs, and why

- **MCP SDK import.** The brief (and `CLAUDE.md`'s own caution note)
  expected `from mcp.server import MCPServer` with `mcp[cli]>=2,<3`. The
  real installed package is **`mcp==1.30.0`**, and that class does not
  exist in it. Verified real entry point:
  `from mcp.server.fastmcp import FastMCP`. `pyproject.toml` is pinned to
  `mcp[cli]>=1.2,<2` to match what actually installs.
- **Facility/hospital naming.** docs/05 says to generalize `hospitals` →
  `facilities`. The table is renamed, but the foreign-key columns on
  `price_records`, `medicare_benchmarks`, `cases`, and `hospital_sources`
  keep the name `hospital_id` — docs/02's own JSON contract names a match
  field `hospital_exact` and a benchmark basis string
  `"hospital_discounted_cash"`, so renaming the FK would have silently
  drifted from a contract docs/02 states explicitly. All *new* ProofMap
  tables (`case_evidence`, `facility_assistance`) use `facility_id`, since
  they were born after the generalization.
- **Confidence base for "payer matched, plan unmatched."** docs/03's
  numeric confidence table has no row for this case — it's only described
  in prose under the commercial benchmark order ("lower confidence +
  warning"). The narrative minimums section says missing payer/plan belongs
  at Medium, not High, so this case uses tier 3's base (0.80) rather than
  tier 2's cash-price base (0.90). `services/price_matching.py` has a
  comment explaining the choice.
- **`peer_percentile` in the review-score formula is always 0/disabled.**
  docs/03 defines the formula's `peer_component` in terms of a
  `peer_percentile` input but never says how to compute one, and with a
  2-hospital seed there's no defensible percentile to compute. Marked with
  a `ponytail:`-style comment in `services/analysis.py` naming the ceiling
  (2-hospital seed) and the upgrade path (compute a real percentile once
  more peer hospitals are ingested).
- **`PriceRecord.charge_scope`.** docs/02's `price_records` column list
  doesn't include `charge_scope` (only `bill_lines` has it). Added it
  anyway, because "never match facility and professional charges as
  equivalent" (docs/03, Match dimensions) is unenforceable for price-record
  matching without it, and the CMS V3 fixture already carries a
  `billing_class` field that maps directly onto it.
- **BillLine PATCH version guard uses an integer counter, not a
  timestamp.** docs/04 just says "with a version guard." An
  `updated_at`-based guard was tried first and proved flaky: two PATCHes
  inside the same wall-clock second (routine in an automated test, and
  possible in real fast double-clicks) produced identical truncated
  timestamps and silently passed the guard. Switched to an explicit
  `version` integer column, incremented on every successful PATCH — a
  standard optimistic-lock pattern that isn't clock-resolution-dependent.
- **Non-price finding "line totals that do not reconcile with the declared
  total" is not implemented.** docs/02's data contract has no field
  anywhere (case, bill_line, or otherwise) representing a bill's declared
  statement total to reconcile against. Implementing this would mean adding
  a field docs/02 never asked for. The other three deterministic findings
  (exact duplicate line, missing code, unknown care setting,
  facility/professional ambiguity) are implemented and tested.
- **`GET /cases/{id}/packet/latest.pdf` returns a clean `501`** — this is
  explicitly allowed by docs/04 ("P1; return a clean 501 if unimplemented").
- **Postgres is wired but not live-tested.** `DATABASE_URL` alone selects
  the driver (added `psycopg[binary]` so `postgresql+psycopg://...` works
  with zero code changes), and `docker-compose.yml` has a `postgres` profile
  service. There was no Postgres instance available in this environment to
  run a live smoke test against, so only the SQLite path has an executed
  integration test suite behind it. `uv sync --no-dev --frozen` (the
  Dockerfile's install line) was verified locally.
- **`docker build` / `docker compose up` themselves are untested.** The
  Docker CLI is present in this environment but its daemon is not running
  (`docker build` fails with "no such file or directory" on the daemon
  socket) — starting a system daemon was out of scope for a code-only task.
  The Dockerfile and compose file were reviewed carefully and their
  individual pieces (the `uv sync --no-dev --frozen` line, the seed-then-run
  command) were each verified to work outside the container.
- **`ruff check .` needed 3 deliberate `[tool.ruff.lint] ignore` entries**
  beyond the defaults: `B008` (FastAPI's own `Depends(...)`-as-default
  idiom, not a bug), `DTZ003`/`DTZ011` (this codebase deliberately uses
  naive UTC datetimes everywhere, a consistent internal convention), and
  `PLW1510` (the test helper's `subprocess.run` calls assert on
  `returncode` explicitly on the next line — that *is* the check ruff wants
  inline). All genuine issues ruff found (unused imports, `dict()` →
  literal, a PEP-695 generic-class opportunity) were fixed, not ignored.
- **Stage 10 (optional adapters) was skipped entirely**, per BUILD_BACKEND's
  own instruction: every P0 acceptance criterion above is green, and the
  brief says to skip without hesitation when that's true. Neither the
  Anthropic PDF-extraction adapter nor the Turquoise adapter is implemented;
  both are behind the `EXTERNAL_PDF_EXTRACTION_ENABLED=false` /
  `TURQUOISE_ENABLED=false` flags already present in `.env.example`, and
  nothing in P0 depends on them — the demo works fully offline without them.

### Seed data: synthetic vs. verified

- **Verified (`is_synthetic=false`):** 21 price rows for five shared CPTs
  (71046, 80053, 74177, 99284, 99285), including gross/cash prices at both
  hospitals and the exact LewisGale Cigna/NPR negotiated hero rate. Every row
  has a source URL, MRF last-updated/retrieval date, and record locator; both original
  MRF SHA-256 hashes are in `data/seed/provenance.json`.
- **Synthetic price rows:** none in the normal seed. The small JSON/CSV MRFs in
  `data/fixtures/` remain isolated parser fixtures. The patient statement is
  deliberately synthetic and labeled as such. `regional_benchmarks`,
  `medicare_benchmarks`, and
  `plan_benefit_profiles` have **zero rows** — no compatible public
  aggregate was available to ingest in this environment, so those code
  paths are exercised by unit tests but return empty/`insufficient_data` in
  the live seed.
- **Facility verification:** both hospital records now cite their official
  `cms-hpt.txt` sources and verification date. The three urgent-care records
  remain unverified placeholders with null verification metadata and no price
  rows; they still require the docs/99 human check. One urgent-care location
  (`Family Urgent Care of Montgomery County`) is seeded with **zero** price
  rows on purpose, to exercise the honest "no public price found" state —
  that is a deliberate design choice from docs/05, not a data gap.

### MCP SDK

- Installed version: **`mcp==1.30.0`**.
- Real import path: **`from mcp.server.fastmcp import FastMCP`**.
- `pyproject.toml` pins `mcp[cli]>=1.2,<2` (the brief's `>=2,<3` does not
  match what installs for this SDK's current release line).
