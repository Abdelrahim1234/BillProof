# 04 — Current REST and MCP contract

## Architecture

```text
browser -> same-origin Next.js /api/v1/* proxy -> FastAPI routes --┐
                                                                  ├-> repositories -> selected store
MCP client -> FastMCP tools -> shared deterministic services ------┘
                                                local JSON files or MongoDB
```

REST and MCP call the same repositories and domain services. MCP never calls
localhost HTTP, and there is no fake `/mcp` REST endpoint. The browser never
receives the backend origin or raw case token: the Next.js proxy stores the
token in an HttpOnly cookie and adds the bearer header server-side.

The default store is the local JSON-file adapter in `store.py`. MongoDB is an
explicit server-only option; setting `MONGODB_URI` alone does not activate it.

## Current repository layout

```text
backend/
├── pyproject.toml · uv.lock · .env.example · Dockerfile · docker-compose.yml
├── data/seed/              verified small extracts and provenance
├── data/fixtures/          synthetic parser/demo inputs only
├── scripts/                seed, readiness, ingestion, retention, Mongo admin
├── src/billproof/
│   ├── config.py · store.py · models.py · errors.py
│   ├── api/routes/         REST handlers
│   ├── repositories/       file/Mongo-neutral data access
│   ├── services/           deterministic analysis and explanation grounding
│   ├── schemas/            request/response contracts
│   └── mcp_server.py       FastMCP server over the same services
└── tests/unit/ · tests/integration/

frontend/
├── app/                    patient flow, projector screen, same-origin API route
├── components/             review, evidence, packet, explainer, wall UI
├── lib/                    typed client and hardened backend proxy helpers
└── tests/                  proxy and client contract tests
```

## REST — public

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Process health |
| GET | `/api/v1/ready` | Store, market, and seed readiness |
| GET | `/api/v1/hospitals` | Active-market facility search |
| GET | `/api/v1/hospitals/{hospital_id}` | Active facility and source metadata |
| GET | `/api/v1/prices/search` | Eligible, cited public-price evidence |
| GET | `/api/v1/demo/samples` | Stable judge-sample metadata |
| POST | `/api/v1/cases` | Create an anonymous case |
| POST | `/api/v1/demo/cases` | Create the offline synthetic hero case |
| GET | `/api/v1/map/search` | Nearby active-market facilities |
| GET | `/api/v1/map/legend` | Map evidence legend |
| GET | `/api/v1/facilities/{id}/price-evidence` | Facility price evidence |
| GET | `/api/v1/areas/{type}/{code}/benchmarks` | Available area benchmarks |
| POST | `/api/v1/estimates/out-of-pocket` | Deterministic plan cost-share estimate |
| GET | `/api/v1/screens/{room}/latest` | Privacy-reduced presentation copy |
| DELETE | `/api/v1/screens/{room}` | Clear a presentation room |

Only LewisGale Montgomery and Carilion NRV belong to the active
`nrv_core_v1` market. Public evidence is returned only when it is
non-synthetic, belongs to an active source manifest, and has complete
provenance.

## REST — protected

Direct API clients send `Authorization: Bearer <case_access_token>`. Browser
clients use the same paths through the Next.js proxy and its HttpOnly session
cookie.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/cases/{id}` | Case metadata |
| DELETE | `/api/v1/cases/{id}` | Immediate cascade deletion |
| POST | `/api/v1/cases/{id}/bill/extract` | Bounded upload to editable candidates |
| POST | `/api/v1/cases/{id}/bill/manual` | Submit confirmed manual lines |
| GET | `/api/v1/cases/{id}/bill` | Read confirmed lines |
| PATCH | `/api/v1/cases/{id}/bill` | Correct one line with integer version guard |
| POST | `/api/v1/cases/{id}/lines/bulk` | Confirm extracted candidates |
| POST | `/api/v1/cases/{id}/analysis` | Run deterministic analysis |
| GET | `/api/v1/cases/{id}/analysis/latest` | Latest analysis |
| GET | `/api/v1/cases/{id}/activity` | Safe activity receipts |
| POST | `/api/v1/cases/{id}/packet` | Generate a deterministic packet |
| GET | `/api/v1/cases/{id}/packet/latest` | Latest packet JSON and Markdown |
| GET | `/api/v1/cases/{id}/packet/latest.pdf` | Clean `501`; PDF is not implemented |
| POST | `/api/v1/cases/{id}/lines/{line_id}/explain` | Grounded line explanation |
| POST | `/api/v1/cases/{id}/ask` | Grounded case question |
| POST | `/api/v1/cases/{id}/publish` | Publish a privacy-reduced display copy |
| POST | `/api/v1/cases/{id}/evidence` | Add selected map evidence |
| DELETE | `/api/v1/cases/{id}/evidence/{evidence_id}` | Remove selected evidence |

Case tokens use at least 32 random bytes, are returned only at creation, and are
stored only as a SHA-256 hash. Missing credentials return `401`; an invalid or
wrong-case credential returns `403`. Cases expire after 24 hours by default and
the purge script performs the full child-record cascade.

## Analysis and explanation rules

All amounts, comparisons, score components, labels, citations, and eligibility
results are produced by deterministic code. The default explanation provider is
server-local and deterministic. Gemini is optional, requires explicit case
consent and server-only configuration, and can only verbalize already-computed
normalized data. Questions and answers are not persisted.

## MCP server

The installed SDK uses `from mcp.server.fastmcp import FastMCP`. The server is
named `billbuster` and exposes typed structured output.

### Tools

`find_hospital` · `lookup_public_prices` · `compare_bill_line` · `analyze_case`
· `explain_bill_line` · `ask_about_case` · `find_assistance_options` ·
`build_negotiation_packet` · `get_source_provenance` ·
`find_nearby_facilities` · `get_local_price_landscape` ·
`estimate_plan_cost_share` · `compare_area_prices` ·
`add_map_evidence_to_case` · `explain_price_source`

Protected tools validate both `case_id` and `access_token`. Raw bill files and
raw document text are never MCP arguments. Protected calls record safe activity
receipts without prompts, answers, arguments, or chain-of-thought.

### Resource and prompt

- `methodology://pricing-comparison` explains amount types, compatibility,
  matching, scoring, privacy, and limitations.
- `prepare_hospital_call(case_id, language, goal)` instructs the host to call
  protected tools with credentials supplied out of band, cite returned evidence,
  and avoid unsupported numbers.

## Security boundary

- Explicit CORS origins; local servers bind to loopback by default.
- The BFF accepts only a credential-free backend origin and forwards an explicit
  header allowlist.
- Mutating browser requests require a matching effective origin.
- Request and response bodies are size-bounded and upstream calls time out.
- Returned citations have query strings stripped; signed download credentials
  never enter API, screen, packet, or browser responses.
- There is no arbitrary URL-fetch endpoint. MRF ingestion is an admin CLI only.
- Case deletion and expiry purge all private child records and presentation
  copies.

## Verification gate

The release gate is the executable behavior, not an aspirational adapter list:

- 119 backend unit/integration/MCP/storage tests and Ruff.
- 16 frontend proxy/client tests, TypeScript, and production build.
- Readiness verifies both active hospitals, 21 real rows, the two hero codes,
  stable query-free citations, commercial/no-EOB and self-pay behavior, and
  cascade deletion.
- A production-mode same-origin smoke test covers case creation, analysis,
  packet generation, deterministic explanation, presentation publish/poll, and
  deletion.
