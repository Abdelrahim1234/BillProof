# API contract (current implementation)

All application routes are under `/api/v1`. When a response has a body, it is
wrapped as `{"data": ..., "request_id": "..."}` on success or
`{"error": {"code", "message", "field", "retryable", "details"},
"request_id": "..."}` on failure. Successful `204` deletes have no body.

REST and MCP use the same `services/` and `repositories/` code. FastAPI serves
the generated OpenAPI document at `/openapi.json` and interactive docs at
`/docs`.

## Runtime evidence boundary

The active market is `nrv_core_v1` and contains only LewisGale Hospital
Montgomery and Carilion New River Valley Medical Center. Runtime hospital
lookup and case creation reject facilities outside that list. Inova Fairfax
and urgent-care identities may remain stored, but are not exposed as active
runtime choices.

Public price search, matching, peer comparisons, and map evidence use the
repository-level evidence guard. An eligible row must:

- have `is_synthetic=false`;
- belong to the active market where the caller requires market scope;
- carry source type, source URL, citation URL, and a row locator; and
- resolve to an active source manifest with a hash.

Public citations use stable, query-free URLs. Signed retrieval query strings
are not returned by the API.

## Authentication and browser boundary

Direct backend clients authenticate case-scoped routes with
`Authorization: Bearer <access_token>`. `POST /cases` and
`POST /demo/cases` return that opaque token once; only its SHA-256 hash is
stored. A case UUID alone is not authorization.

The Next.js frontend does not expose that token to browser JavaScript. Its
same-origin `/api/v1/*` proxy removes `access_token` from case-creation
responses, stores it in an HttpOnly same-site cookie, and adds the bearer
header server-side on protected case requests.

Hospital, price, demo-catalogue, health, map-read, and presentation-screen read
routes are public. Publishing a case to a screen is case-authenticated. Screen
rooms are capability URLs with 12-32 character codes; production should use a
random code. Anyone holding that capability can read or clear its display copy.

## Routes implemented

```text
GET    /api/v1/health
GET    /api/v1/ready
       -> {status, db, backend, market_id, seeded}

GET    /api/v1/demo/samples
POST   /api/v1/demo/cases
       optional body: {"sample": "nrv_cash_review"}

POST   /api/v1/cases
GET    /api/v1/cases/{case_id}                         bearer required
DELETE /api/v1/cases/{case_id}                         bearer; full case cascade

POST   /api/v1/cases/{case_id}/bill/extract            bearer; upload -> candidates
POST   /api/v1/cases/{case_id}/bill/manual             bearer; manual confirmed lines
POST   /api/v1/cases/{case_id}/lines/bulk              bearer; confirm candidates
GET    /api/v1/cases/{case_id}/bill                    bearer
PATCH  /api/v1/cases/{case_id}/bill                    bearer; optimistic-lock update

POST   /api/v1/cases/{case_id}/analysis                bearer; run and persist
GET    /api/v1/cases/{case_id}/analysis/latest         bearer

POST   /api/v1/cases/{case_id}/packet                  bearer
GET    /api/v1/cases/{case_id}/packet/latest           bearer
GET    /api/v1/cases/{case_id}/packet/latest.pdf       bearer; 501 NOT_IMPLEMENTED

POST   /api/v1/cases/{case_id}/lines/{line_id}/explain bearer; consent rules apply
POST   /api/v1/cases/{case_id}/ask                     bearer; consent rules apply
GET    /api/v1/cases/{case_id}/activity                bearer; safe receipts only

POST   /api/v1/cases/{case_id}/publish                 bearer; privacy-reduced copy
GET    /api/v1/screens/{room_code}/latest              token-free display copy
DELETE /api/v1/screens/{room_code}                     clear presentation room

GET    /api/v1/hospitals
GET    /api/v1/hospitals/{hospital_id}
GET    /api/v1/prices/search

GET    /api/v1/map/search
GET    /api/v1/map/legend
GET    /api/v1/facilities/{facility_id}/price-evidence
GET    /api/v1/areas/{geography_type}/{geography_code}/benchmarks
POST   /api/v1/estimates/out-of-pocket
POST   /api/v1/cases/{case_id}/evidence                bearer
DELETE /api/v1/cases/{case_id}/evidence/{evidence_id}  bearer
```

The presentation copy never contains a case token or private case, analysis,
line, or price-record identifier. User-entered free-text line descriptions are
removed before publication; bundled synthetic demo descriptions may be retained.

## Routes from `CODEX_IMPLEMENTATION_SPEC.md` section 13 not implemented

```text
GET    /api/v1/cases/{case_id}/documents/{document_id}/extraction
PATCH  /api/v1/cases/{case_id}/documents/{document_id}/fields
POST   /api/v1/cases/{case_id}/coverage/confirm
POST   /api/v1/cases/{case_id}/explanations
GET    /api/v1/cases/{case_id}/map
```

The `/documents/*` and `/coverage/confirm` routes require a multi-document
bill/EOB pipeline that is not present. The current upload flow handles a
hospital bill and returns editable candidate lines. The exact aggregate
`/explanations` route is absent; focused line explanation and case-question
routes are implemented at `/lines/{line_id}/explain` and `/ask`. A case-scoped
map aggregate is absent; callers use `/map/search` and
`/facilities/{facility_id}/price-evidence`.

## MCP tools

`src/billproof/mcp_server.py` exposes 15 tools through FastMCP:

```text
find_hospital
lookup_public_prices
compare_bill_line
analyze_case
explain_bill_line
ask_about_case
find_assistance_options
build_negotiation_packet
get_source_provenance
find_nearby_facilities
get_local_price_landscape
estimate_plan_cost_share
compare_area_prices
add_map_evidence_to_case
explain_price_source
```

Protected tools take `case_id` and `access_token` and validate the same stored
token hash as REST. Activity receipts contain safe summaries, not questions,
answers, uploaded text, credentials, or chain-of-thought.

The lock file currently resolves `mcp==1.30.0`, whose high-level entry point is
`from mcp.server.fastmcp import FastMCP`. `mcp.server.MCPServer` is not an
export in this SDK line.

## Persistence

`billproof/store.py` is the single storage entry point for REST, MCP, seed, and
admin commands. `STORAGE_BACKEND=file` is the explicit default and persists
two gitignored JSON stores. `STORAGE_BACKEND=mongodb` selects PyMongo's async
client and the same public/private database split; merely setting
`MONGODB_URI` does not switch storage.

MongoDB configuration and index initialization are documented in
`ATLAS_SETUP.md`. `scripts.mongo_inventory` produces redacted metadata only;
`scripts.mongo_cleanup` defaults to a no-write plan and supports reviewed,
reversible quarantine rather than deletion.
