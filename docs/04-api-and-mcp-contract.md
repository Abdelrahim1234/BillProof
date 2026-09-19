# 04 — REST and MCP contract

## Architecture

```text
FastAPI routes ─┐
                ├─> shared repositories + deterministic domain services ─> DB
MCP tools ──────┘

offline ingestion CLI ─> curated normalized price snapshots ─> DB
optional extractors / data providers implement adapters behind protocols
```

REST and MCP import and call the **same service classes**. MCP tools never call
localhost REST. There is no fake `/mcp` REST route.

## Repository layout

```text
backend/
├── pyproject.toml · uv.lock · .env.example · .gitignore
├── Dockerfile · docker-compose.yml · README.md
├── data/
│   ├── seed/{hospitals,hospital_sources,provenance}.json
│   │         {public_prices,medicare_benchmarks}.csv
│   └── fixtures/{demo_bill.txt,demo_bill.pdf,demo_bill_expected.json,
│                 cms_v3_small.json,cms_tall_small.csv}
├── scripts/{seed,ingest_mrf,sync_cms_hospitals,
│            ingest_medicare_benchmarks,purge_expired_cases}.py
├── src/billproof/
│   ├── config.py db.py models.py errors.py logging_config.py
│   ├── api/{main,dependencies}.py
│   ├── api/routes/{health,hospitals,cases,bills,analysis,packets,activity}.py
│   ├── schemas/{common,cases,bills,prices,analysis,packets}.py
│   ├── repositories/{hospitals,prices,cases}.py
│   ├── services/{code_normalizer,extraction,price_matching,benchmarking,
│   │             analysis,packet_builder,case_auth,activity,privacy}.py
│   ├── adapters/{cms_provider_data,cms_mrf,cms_medicare,
│   │             anthropic_pdf,turquoise}.py
│   ├── templates/negotiation_packet_{en,es}.md.j2
│   └── mcp_server.py
└── tests/{conftest.py,unit/,integration/}
```

Adapt only if the existing repository makes another layout clearly preferable.

## REST — public

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Process health |
| GET | `/api/v1/ready` | DB and seed readiness |
| GET | `/api/v1/hospitals` | Search by name, city, state, ZIP |
| GET | `/api/v1/hospitals/{hospital_id}` | Hospital + source metadata |
| GET | `/api/v1/prices/search` | Read-only cited price search (debug/methodology) |
| POST | `/api/v1/cases` | Create an anonymous case |
| POST | `/api/v1/demo/cases` | Deterministic judge sample case |

## REST — protected (`Authorization: Bearer <case_access_token>`)

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/cases/{id}` | Case status/metadata |
| DELETE | `/api/v1/cases/{id}` | Immediate deletion |
| POST | `/api/v1/cases/{id}/bill/extract` | Multipart upload → editable candidates; raw file never retained |
| POST | `/api/v1/cases/{id}/bill/manual` | Submit a complete manual bill |
| GET | `/api/v1/cases/{id}/bill` | Confirmed structured bill fields |
| PATCH | `/api/v1/cases/{id}/bill` | Correct fields, with a version guard |
| POST | `/api/v1/cases/{id}/lines/bulk` | Confirm/add extracted candidates |
| POST | `/api/v1/cases/{id}/analysis` | Run deterministic analysis synchronously |
| GET | `/api/v1/cases/{id}/analysis/latest` | Latest analysis |
| GET | `/api/v1/cases/{id}/activity` | Safe activity receipts |
| POST | `/api/v1/cases/{id}/packet` | Generate packet for goal/language |
| GET | `/api/v1/cases/{id}/packet/latest` | Packet JSON + Markdown |
| GET | `/api/v1/cases/{id}/packet/latest.pdf` | P1; return a clean 501 if unimplemented |

No async job queue in P0. Synchronous extraction/analysis with a frontend
loading state. On timeout, return a clean retryable error.

## Case authentication

≥32 random bytes. Plaintext returned only at creation. Store only a SHA-256/HMAC
hash. Constant-time comparison. `401` for missing credentials, `403` for invalid.
24-hour default expiry plus a purge command.

## Demo endpoint

`POST /api/v1/demo/cases` clones a stable synthetic case + bill fixture into a
fresh case and returns:

```json
{"data": {"case_id": "uuid", "access_token": "one-time-token",
          "expires_at": "ISO-8601", "is_demo": true},
 "request_id": "..."}
```

It must work with **no internet access at all**.

## Packet

Deterministic Jinja2. A model may later rewrite tone, but no model invents
numbers, citations, eligibility, or legal claims.

`PacketRequest`: `goal` ∈ `billing_review | cash_price_match | discount |
payment_plan | financial_assistance | insurance_appeal`; `language` ∈ `en|es`;
`additional_context` optional, ≤1000 chars.

Packet contents, in order: plain-language summary · assumptions and missing
fields · line-item comparison table · benchmark type, date, applicability, source ·
questions for billing/coding review · itemized-bill checklist · self-pay discount,
financial-assistance, and interest-free payment-plan questions · insurer EOB
reconciliation checklist when relevant · phone script · written review-request
template · blank local placeholders for name/account number (never stored) ·
source list, limitations, disclaimer.

## MCP server

Use the official SDK — **verify the actual import path against the installed
package** (see CLAUDE.md). Typed Pydantic return models so the server publishes
and validates structured output.

### Core tools
1. `find_hospital(query, state=None, limit=10)`
2. `lookup_public_prices(hospital_id, code_type, code, modifier=None, care_setting=None, payer_name=None, plan_name=None)`
3. `compare_bill_line(hospital_id, code_type, code, comparison_amount, comparison_amount_type, units, coverage_type, modifier=None, care_setting=None, payer_name=None, plan_name=None, service_month=None)`
4. `analyze_case(case_id, access_token)`
5. `find_assistance_options(hospital_id)`
6. `build_negotiation_packet(case_id, access_token, goal, language)`
7. `get_source_provenance(price_record_id)`

### ProofMap tools (see docs/05)
`find_nearby_facilities` · `get_local_price_landscape` · `estimate_plan_cost_share`
· `compare_area_prices` · `add_map_evidence_to_case` · `explain_price_source`

### Resource
`methodology://pricing-comparison` — explains charge types, amount
compatibility, matching, scoring, privacy, limitations.

### Prompt
`prepare_hospital_call(case_id, access_token, language, goal)` — instructs the
host to analyze the case, cite returned evidence, disclose limitations, and
generate no unsupported number.

### Requirements
- MCP tools call shared domain services directly.
- Protected case tools validate the case token; public lookups may be unauthenticated.
- **Never accept a raw bill file or raw document text as an MCP argument.**
- Record safe `activity_receipts` with `transport=mcp` for protected tools.
- Bind Streamable HTTP to `127.0.0.1` by default; stdio for the local demo;
  Streamable HTTP for deployment. No legacy SSE-only server.
- Prefer separate API and MCP processes. If mounting the MCP ASGI app into
  FastAPI, enter the MCP session-manager lifespan correctly or the first request
  fails.
- Every tool response includes: typed result data, source identifiers/URLs,
  effective + retrieval dates, match method and confidence, limitations and
  missing inputs, and a safe user-visible activity summary.

## Security

Explicit CORS origins · local servers bound to loopback · no arbitrary URL-fetch
endpoint · MRF ingestion only via admin CLI · returned source links come only
from trusted seeded/ingested records · opaque UUIDs · token hashes only ·
rate-limiting is P1 but design middleware so it can be added.

## Integration test list

**API:** health/ready · demo case fully offline · case creation returns token
once · missing token `401`, wrong token `403` · manual bill add/get/patch ·
text-PDF extraction and candidate confirmation · full analysis + packet flow ·
unsupported/no-price case returns `insufficient_data` not `500` · oversize upload
`413` · unsupported media `415` · temp file deleted after success **and**
failure · raw bill text absent from the DB · money round-trips in integer cents
with no float · case deletion and purge · SQLite full workflow · Postgres smoke
path via Docker Compose.

**MCP:** official client completes initialization · `list_tools` returns all
tools with structured schemas · `find_hospital` and `lookup_public_prices` return
typed content · `compare_bill_line` equals the shared-service/REST result for the
same inputs · protected tools reject a wrong token · `analyze_case` records an
MCP receipt · methodology resource reads · prompt retrieves · no tool fabricates
a source URL.
