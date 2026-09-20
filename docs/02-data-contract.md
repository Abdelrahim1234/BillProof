# 02 — Data contract: enums, JSON, models, ingestion

## Canonical enums

```text
CodeType:   CPT | HCPCS | CPT_HCPCS | MS_DRG | APC | REVENUE | NDC | LOCAL | UNKNOWN
CareSetting: inpatient | outpatient | emergency | unknown
CoverageType: uninsured | commercial | medicare_advantage | medicaid_managed |
              medicare_ffs | other | unknown
ChargeType: gross | discounted_cash | payer_negotiated | deidentified_min |
            deidentified_max | allowed_p10 | allowed_median | allowed_p90 |
            medicare_avg_payment
Confidence: high | medium | low | insufficient
AnalysisStatus: completed | partial | insufficient_data

# ProofMap additions
FacilityType: hospital | hospital_outpatient | urgent_care | other
MapAmountType: gross | discounted_cash | payer_negotiated | deidentified_min |
               deidentified_max | allowed_p10 | allowed_median | allowed_p90 |
               medicare_ffs_observed | apcd_allowed_aggregate
EvidenceAvailability: exact | partial | regional_context | unavailable
ObservedOrPublished: published | observed_aggregate | user_entered
```

## JSON rules

- snake_case keys everywhere.
- Money object at every boundary: `{"amount_cents": 115000, "currency": "USD"}`.
- `Decimal` internally; storage adapters serialize exact decimal values and the
  API converts them to integer cents. Never a float for money or percentage.
  Percentages are decimal strings, e.g. `"108.70"`.
- Success: `{"data": {...}, "request_id": "opaque"}`
- Error: `{"error": {"code": "MACHINE_CODE", "message": "...", "field": null,
  "retryable": false, "details": {}}, "request_id": "opaque"}`

## Pydantic models (minimum)

`Money`, `SourceCitation`, `ActivityReceipt`, `CaseCreate`, `CaseCreated`,
`BillLineInput`, `ExtractedLineCandidate`, `BillDocument`, `PriceReference`,
`BenchmarkSummary`, `MatchDetails`, `LineComparison`, `AnalysisResponse`,
`PacketRequest`, `PacketResponse`.

### LineComparison shape

```json
{
  "line_id": "uuid",
  "comparison_status": "compared",
  "comparison_subject": {
    "type": "billed_amount",
    "money": {"amount_cents": 240000, "currency": "USD"}
  },
  "benchmark": {
    "basis": "hospital_discounted_cash",
    "low": {"amount_cents": 115000, "currency": "USD"},
    "median": {"amount_cents": 115000, "currency": "USD"},
    "high": {"amount_cents": 115000, "currency": "USD"},
    "sample_size": 1,
    "match_tier": "same_hospital_exact_code_setting",
    "confidence": "high",
    "limitations": ["A cash price is not a final insured out-of-pocket amount."]
  },
  "difference": {"amount_cents": 125000, "currency": "USD"},
  "percent_above_benchmark": "108.70",
  "review_score": 77,
  "review_label": "high_review_opportunity",
  "match": {
    "hospital_exact": true, "code_exact": true, "setting_exact": true,
    "modifier_exact": null, "payer_exact": null, "plan_exact": null,
    "factors_used": ["hospital", "code", "setting"],
    "missing_factors": ["modifier"]
  },
  "references": [], "suggested_questions": [], "warnings": []
}
```

For an insured case with no allowed amount and no compatible payer/plan
reference: return contextual rates only. `difference`, `review_score`, and
`percent_above_benchmark` are null.

## Storage document model

The same Pydantic documents are persisted by the local JSON-file adapter and
the optional MongoDB adapter. Collection names below are logical contracts, not
SQL tables.

### `hospitals` (generalize to `facilities` — see docs/05)
`id` UUID · `facility_id` (CMS CCN, nullable/unique) · `organization_npi` ·
`name` `address` `city` `state` `zip_code` · `hospital_type` `ownership` `phone` ·
`latitude` `longitude` · `financial_assistance_url` `billing_url` ·
`cms_updated_at` `created_at`.

Never silently equate CCN, NPI, EIN, or a health-system identifier.

### `hospital_sources`
`id` `hospital_id` · `source_type` (`cms_mrf | cms_provider | cms_medicare | ...`) ·
`source_url` `schema_version` `file_date` `retrieved_at` `sha256` `active`.

### `price_records`
`id` `hospital_id` · `code_type` `code` `modifier` `description` `care_setting` ·
`charge_type` · `payer_name` `payer_normalized` `plan_name` `plan_normalized` ·
`amount` nullable `Decimal` · `currency` `rate_unit` `rate_method`
`allowed_count` · `mrf_date` `source_url` `source_record_locator` `is_synthetic`
`created_at`.

Indexes: `(hospital_id, code_type, code)`,
`(code_type, code, care_setting, charge_type)`,
`(payer_normalized, plan_normalized)`.

### `medicare_benchmarks`
`id` `hospital_id` · `code_type` (P0: only `MS_DRG` or `APC`) · `code`
`service_count` · `average_submitted_charge` `average_total_payment`
`average_medicare_payment` · `data_year` `source_url` `suppressed`.

### `cases`
`id` UUID · `access_token_hash` · `hospital_id` · `coverage_type` `payer_name`
`plan_name` `care_setting` · `service_month` (`YYYY-MM`, **not** a full date) ·
`language` (`en|es`) · `external_processing_consent` · `created_at` `expires_at`.

**Forbidden columns:** patient name, birth date, street address, account number,
member ID, email, phone.

### `bill_lines`
`id` `case_id` · `code_raw` `code` `code_type` `modifiers` JSON · `description`
`units` `rate_unit` · `billed_amount` `allowed_amount` `insurer_paid`
`patient_responsibility` · `charge_scope` (`facility|professional|unknown`) ·
`care_setting` · `extraction_confidence` `needs_manual_review` `confirmed` ·
`created_at` `updated_at`.

### `analyses`
`id` `case_id` `input_hash` `status` `result_json` `created_at`.

### `packets`
`id` `case_id` `goal` `language` `packet_json` `markdown` `created_at`.

### `activity_receipts`
`id` `case_id` · `transport` (`rest|mcp|internal`) · `tool_name` `display_name`
`status` `summary` · `source_ids` JSON · `started_at` `completed_at`.

Receipts are safe summaries only — never chain-of-thought, prompts, raw args,
tokens, DB paths, or logs. Example summaries: "Read 3 bill line items",
"Resolved LewisGale Hospital Montgomery", "Looked up HCPCS/CPT 99285",
"Matched one hospital cash-price record", "No defensible match was found for one
line", "Prepared an English negotiation packet from 2 cited findings".

The UI may label a receipt "MCP" only when `transport=mcp`; otherwise "Analysis
activity".

## Code normalization

- Trim, uppercase, strip irrelevant whitespace/punctuation; preserve raw input.
- Separate modifiers from the base code.
- Five numeric chars with no declared system → `CPT_HCPCS`, never auto-`CPT`.
- Letter + four digits may be HCPCS Level II.
- Revenue codes stay four digits with leading zero.
- Pad DRG/APC only when the source explicitly declares the type.
- Preserve NDC 10- vs 11-digit source representation.
- Never translate across code systems via description similarity. Description
  similarity is a manual suggestion only — never an automatic comparison or score.
- Do not bundle a proprietary CPT description dictionary. Use descriptions from
  the bill/MRF and permitted CMS HCPCS/MS-DRG resources only.

## Ingestion

Sources for P0:
1. CMS Hospital General Information dataset `xubh-q36u` (identity, CCN, address,
   phone, type, ownership, rating).
2. Direct CMS-format hospital MRFs (V3 schema; 2026 template may include allowed
   p10/median/p90/count — not on every row).
3. Optional curated CMS Medicare MS-DRG / APC aggregates, labeled Medicare FFS.
4. Verified hospital financial-assistance and billing pages in seed metadata.

Rules:
- **Never download a large file during an API or MCP request.** Ingestion is an
  admin CLI only (`scripts/ingest_mrf.py`).
- Stream JSON with `ijson`. Support the included tall-CSV fixture too.
- Support a code allowlist so the snapshot stays small.
- Algorithm/percentage rows: store with a null dollar amount, show the method as
  context, exclude from numeric comparison.
- Preserve for every row: hospital/location identity; code type, code, modifier,
  setting, description, unit; charge type, payer, plan, amount, allowed count;
  MRF/schema version and file date; source page/file URL; retrieval timestamp;
  SHA-256 of the source file; source record locator; `is_synthetic` flag.
- Every non-synthetic price fixture must come from an actual cited source row.
  If a row cannot be verified and cited, mark `is_synthetic=true` and keep it out
  of any claim about real public prices. One verified row beats ten questionable
  ones.
- MRF discovery is decentralized: try `https://<domain>/cms-hpt.txt`, otherwise
  the hospital's verified price-transparency page.
- Do not hardcode release-specific CMS dataset UUIDs — put them in config.

## Bill extraction (local-first)

1. Read in bounded chunks into memory; never write the raw upload to disk.
2. Enforce 15 MB while reading and a 20-page PDF limit.
3. Inspect magic bytes, not extension or MIME.
4. Accept plain text, PDF, PNG, JPEG.
5. `pypdf` for text PDFs.
6. Scanned/image-only with no provider enabled → return `needs_manual_entry`,
   not a 500.
7. Mask identity and account fields **before** parsing or any external call:
   name, DOB, street address, account number, MRN, member ID, email, phone,
   barcode/QR content.
8. Parse labeled codes, descriptions, units, amount categories.
9. Return candidates with confidence and warnings — never silently trust them.
10. Close the upload and drop the in-memory byte buffer in `finally`, on success
    **and** failure.
11. Never persist full extracted text. Never log diagnosis or procedure text.

Optional Anthropic adapter (P1 only, after P0 is green): requires
`EXTERNAL_PDF_EXTRACTION_ENABLED=true`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`,
and case `external_processing_consent=true`. Strict structured output validated
by Pydantic. Treat document content as untrusted data; ignore embedded
instructions. Never log request or response bodies. Never required for demo or
tests.

## `.env.example`

```dotenv
APP_ENV=development
ALLOW_REAL_PHI=false
STORE_RAW_DOCUMENTS=false

STORAGE_BACKEND=file
PRIVATE_DB_NAME=billproof_private
PUBLIC_DB_NAME=billproof_public
MONGODB_URI=
MONGODB_PRIVATE_DATABASE=billproof_private
MONGODB_PUBLIC_DATABASE=billproof_public
MONGODB_ALLOW_REMOTE=false

CORS_ORIGINS=http://localhost:3000,http://localhost:5173
MAX_UPLOAD_MB=15
MAX_PDF_PAGES=20
CASE_TTL_HOURS=24
DEMO_MODE=true
LOG_LEVEL=INFO

EXPLANATION_PROVIDER=deterministic
EXPLANATION_MODEL=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.6-flash

EXTERNAL_PDF_EXTRACTION_ENABLED=false
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=

MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8001

CMS_PROVIDER_DATASET_ID=xubh-q36u
CMS_INPATIENT_DATASET_UUID=
CMS_OUTPATIENT_DATASET_UUID=

TURQUOISE_ENABLED=false
TURQUOISE_CLIENT_ID=
TURQUOISE_CLIENT_SECRET=
TURQUOISE_ORGANIZATION_ID=

ACTIVE_MARKET_ID=nrv_core_v1
ACTIVE_MARKET_FACILITIES=LewisGale Hospital Montgomery,Carilion New River Valley Medical Center
```

## Release seed boundary

- The active market is exactly LewisGale Hospital Montgomery and Carilion New
  River Valley Medical Center (`nrv_core_v1`).
- The runtime seed contains 21 verified, non-synthetic public price rows for
  CPT 71046, 74177, 80053, 99284, and 99285. Full MRFs stay outside Git.
- The hero patient bill is synthetic and identifier-free. Its CPT 80053 line is
  above LewisGale's real cash price; its CPT 71046 line is below it.
- Inova and urgent-care reference identities are out of market and must never
  enter runtime evidence, analysis, presentation, or readiness results.
