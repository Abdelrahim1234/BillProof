# Build prompt — BillBuster backend (full P0)

> Historical implementation brief. The shipped release uses the explicit
> file/Mongo storage contract in `store.py`, not the SQL/Postgres design below.
> Use `README.md`, `PROGRESS.md`, and `docs/04-api-and-mcp-contract.md` for the
> current run, verification, and architecture contract.

Paste this into Claude Code from the repository root. Everything it needs beyond
this file is in `CLAUDE.md` and `docs/`.

---

## Your job

You are the lead backend engineer on a 36-hour hackathon build. Implement the
complete BillBuster P0 backend and MCP server in this repository. Work in the
repo: create code, run it, run tests, fix failures. Do not stop at a plan or
pseudocode. Ask a question only if a real blocker prevents progress.

## Before you write anything

1. Read `CLAUDE.md`. Its invariants override anything below.
2. Inspect the repository as it exists. Preserve unrelated work.
3. Read `docs/02-data-contract.md` and `docs/04-api-and-mcp-contract.md` now.
   Read `docs/01`, `docs/03`, and `docs/05` when you reach the stage that needs
   them — the stage list says which.
4. Write a short plan to `PROGRESS.md` (stage list + current stage + what is
   green), then start immediately.

## Stages

Work in this order. After each stage: run the relevant tests, update
`PROGRESS.md`, and do not move on while something you just wrote is red.

**Stage 1 — Skeleton.** `pyproject.toml` with the pinned stack, `.env.example`,
`.gitignore`, config, db session, logging, error envelope, `/health`, `/ready`.
Get `uv sync --extra dev` and `uv run pytest -q` passing on an empty test suite.

**Stage 2 — Models and schemas.** All tables and Pydantic models from
`docs/02-data-contract.md`, including the ProofMap tables from `docs/05`
(build them now so you never migrate twice). Money as `Decimal`/`Numeric(12,2)`
with an integer-cents boundary type. Enums exactly as written.

**Stage 3 — Seed and ingestion.** `scripts/seed.py`, `scripts/ingest_mrf.py`
(streaming `ijson` for CMS V3 JSON, plus the tall-CSV fixture), source manifest
with SHA-256 hashes, `scripts/purge_expired_cases.py`. **Read
`docs/99-human-tasks.md` first** — real MRF rows must come from the file the team
verified. If `data/seed/public_prices.csv` has no verified rows yet, generate the
full pipeline against the fixtures, mark every generated row `is_synthetic=true`,
and say so loudly in `PROGRESS.md`.

**Stage 4 — Domain services.** Read `docs/03-matching-and-scoring.md`. Code
normalizer, matching tiers, benchmark selection by coverage type, confidence,
review score, non-price findings. **Write the unit tests from the list at the end
of `docs/03` as you go, not after.** This stage is the product; spend the time here.

**Stage 5 — Cases and bills.** Case token auth (32 random bytes, hash-only
storage, constant-time compare, `401` vs `403`, 24-hour expiry), manual bill
entry, local PDF extraction with the privacy flow, the bulk-confirm endpoint, and
`POST /api/v1/demo/cases`. The demo endpoint must work with networking fully
disabled — prove it in a test.

**Stage 6 — Analysis, receipts, packets.** Read `docs/01-product-truth.md` before
writing a single template string. Analysis endpoint, safe activity receipts, and
deterministic Jinja2 packets in English and Spanish.

**Stage 7 — MCP server.** Read the SDK-version warning in `CLAUDE.md` first —
check the installed package's real exports before writing tool code. All seven
core tools, the methodology resource, the prompt, and protocol integration tests
with the official client. `compare_bill_line` must return byte-identical
comparison results to the REST path for the same inputs; test that explicitly.

**Stage 8 — ProofMap.** Read `docs/05-proofmap.md`. Map search with Haversine
radius, facility price-evidence, area benchmarks, out-of-pocket estimate,
add/remove case evidence, and the six ProofMap MCP tools.

**Stage 9 — Harden and document.** Docker + Docker Compose (API + optional
Postgres), README with exact start/test commands and the five-step judge demo,
curl examples, OpenAPI, full test suite green, `ruff check .` clean.

**Stage 10 — Optional adapters.** Anthropic extraction and Turquoise, disabled by
default, behind protocols. Only if every P0 acceptance criterion above is already
green. Skip without hesitation if time is short.

## If your context resets mid-build

Read `CLAUDE.md`, then `PROGRESS.md`, then run `uv run pytest -q`. The first
failing or missing stage is where you are. Do not restart from Stage 1.

## Definition of done

- A new developer can start the system from the README alone.
- Sample and manual-entry flows work offline on SQLite; Postgres works by
  changing `DATABASE_URL` only.
- The sample case produces exactly one exact result, one partial/context result,
  and one `insufficient_data` result.
- Every numeric comparison carries its amount type, applicability, date, and source.
- Amount types are never conflated; no-match returns `insufficient_data`.
- Duplicate and arithmetic findings work.
- English and Spanish packets render.
- Raw uploads are deleted and never persisted or logged.
- Cases expire, can be deleted, and can be purged.
- REST and MCP share the same deterministic services and return identical
  comparison results for identical inputs.
- MCP Inspector or the official client completes a real handshake and tool call.
- All tests and lint checks pass.
- No wording anywhere claims an illegal overcharge or guaranteed savings.

## Final report

When you finish, write a short report covering: what was completed per stage,
test results, every place the implementation differs from these docs and why,
which seed rows are synthetic vs verified, and the exact MCP SDK version and
import path you used.

Begin by inspecting the repository, then start Stage 1.
