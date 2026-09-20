# Security and data retention

## No HIPAA claim

BillBuster does not claim HIPAA compliance anywhere in code, docs, or UI copy.
Free/Flex Atlas tiers and this codebase's current controls are appropriate
for synthetic or properly de-identified demo data only. Real PHI would
require a reviewed Atlas deployment tier, signed BAAs, private networking,
audit logging, KMS-backed encryption, vendor review, and a formal retention
policy -- none of which exist here.

## Defaults

```
APP_ENV=development
ALLOW_REAL_PHI=false
STORE_RAW_DOCUMENTS=false
```

`ALLOW_REAL_PHI` and `STORE_RAW_DOCUMENTS` are read into `Settings` but no
code path currently branches on them -- there is no raw-document persistence
implemented at all yet (see "What's not implemented" below). They exist now
so a future upload/extraction pipeline has a config surface to gate on
instead of inventing one under time pressure later.

## What never gets stored

Per this repo's non-negotiable invariants (`CLAUDE.md`):

- No patient name, DOB, street address, account number, MRN, member ID,
  email, or phone in any collection.
- `Case.access_token_hash` stores only a SHA-256 hash of the opaque bearer
  token (`services/case_auth.py`); the raw token is returned to the client
  exactly once, at creation, and never persisted or logged.
- `services/privacy.mask_identity_fields` redacts email, phone, DOB, SSN,
  labeled IDs, street addresses, and barcodes from extracted bill text
  before it is parsed.
- Uploaded files are read into memory, processed, and the buffer is
  explicitly zeroed (`data = b""`) in a `finally` block after every upload
  route -- nothing is written to disk.

## Money and datetimes

- Every amount is `Decimal` in Python and signed integer cents in MongoDB
  (`MongoModel.MONEY_FIELDS` in `models.py`) -- never a binary float,
  matching CODEX_IMPLEMENTATION_SPEC.md #6.
- New writes use timezone-aware UTC datetimes
  (`datetime.now(timezone.utc)`); the file-backed fake round-trips them
  through JSON as ISO-8601 strings and Pydantic re-parses them on read.

## Retention

```
CASE_TTL_HOURS=24            # case + everything scoped to it expires
ORIGINAL_RETENTION_HOURS=24  # placeholder: no raw-document store exists yet
CASE_RETENTION_DAYS=30
CHAT_RETENTION_HOURS=24      # placeholder: no chat/explanation store exists yet
```

- `cases.expires_at` has a normal lookup index, not a MongoDB TTL index. A
  parent-only TTL can remove the case before the application cascades to its
  child collections, permanently orphaning private records. If an existing
  Atlas database still has `cases_expires_at_ttl`, review and remove that
  index before production; index initialization intentionally will not drop it.
- `scripts/purge_expired_cases.py` is the authoritative cleanup path: it
  finds every case whose `expires_at` has passed and calls
  `repositories.case_records.purge_case_cascade`, which deletes the case's
  `bill_lines`, `analyses`, `packets`, `activity_receipts`, `case_evidence`,
  and `plan_benefit_profiles`, then the case document itself. Run it on a
  schedule (cron, a scheduled task) in any real deployment.
- `DELETE /api/v1/cases/{case_id}` calls the same cascade synchronously, so a
  user-initiated delete does not wait on the TTL monitor.

## Logging

`logging_config.py` configures structured logging; `errors.py` tags every
response with a request ID. No route or service logs a request body, an
access token, extracted bill text, or a Mongo connection string. `store.py`
wraps `MONGODB_URI` as a secret and never logs it.

## Tenancy

Every private-collection query in `repositories/` is scoped by `case_id`
(sourced from the authenticated `Case` the bearer token resolved to, via
`api/dependencies.get_current_case`) -- there is no route that accepts a
raw case UUID as authorization on its own; `Authorization: Bearer <token>` is
required and validated against `access_token_hash` on every case-scoped
route and MCP tool (`mcp_server._require_case`).

## What's not implemented (be honest about the gap)

The following security-relevant surfaces do **not** exist in this codebase
yet:

- No document upload/OCR/redaction pipeline beyond the existing plain-text
  and embedded-PDF-text extraction in `services/extraction.py` (no
  encrypted-PDF detection, no malware scanner interface, no page/document
  classification, no coordinate-tracked OCR).
- No `explanation_turns` collection. The current line-explain and case-question
  routes are stateless: questions and answers are not persisted, so there is
  nothing to apply a chat TTL to yet. `CHAT_RETENTION_HOURS` is a placeholder
  for any future stored conversation feature.
- No object storage / KMS integration (`OBJECT_STORE_*`, `KMS_KEY_ID` are
  unused placeholders in `.env.example`).
- No HMAC-based identifier hashing service for `HMAC_IDENTIFIER_KEY` --
  nothing currently extracts or stores member IDs, account numbers, or claim
  IDs at all, so there is nothing to hash yet.
