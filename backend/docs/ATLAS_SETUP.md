# MongoDB Atlas setup and safe administration

BillBuster uses one storage interface for the API, MCP server, seed scripts,
and admin commands. Local development and tests default to two gitignored JSON
files. A real MongoDB deployment is opt-in through PyMongo's official async
client; setting a URI by itself never changes the backend.

## Local default

```dotenv
STORAGE_BACKEND=file
PRIVATE_DB_NAME=billproof_private
PUBLIC_DB_NAME=billproof_public
```

Tests also set `APP_ENV=test` and `BILLPROOF_DB_DIR` to an isolated temporary
directory. The store refuses MongoDB whenever either test guard is active.

## Atlas configuration

Create a dedicated Atlas project/cluster and a least-privilege application
user with access only to the two BillBuster databases. Restrict the Atlas
network access list to the backend host; never expose Atlas directly to the
browser or use a Vercel client component as a database client.

Put these values only in the backend's secret environment configuration:

```dotenv
STORAGE_BACKEND=mongodb
MONGODB_URI=mongodb+srv://<user>:<password>@<cluster>/?retryWrites=true&w=majority
MONGODB_PRIVATE_DATABASE=billproof_private
MONGODB_PUBLIC_DATABASE=billproof_public
MONGODB_ALLOW_REMOTE=true
MONGODB_SERVER_SELECTION_TIMEOUT_MS=5000
```

`MONGODB_URI` is a `SecretStr`, is never included in health responses or
artifacts, and is never printed by the inventory/cleanup CLIs. Rotate Atlas
credentials and remove temporary network entries after the event.

## Initialize indexes

Index creation is idempotent and never drops indexes or collections:

```bash
uv run python -c '
import asyncio
from billproof import store

async def main():
    await store.connect()
    try:
        print(store.backend_name())
        print(await store.init_indexes())
    finally:
        await store.close()

asyncio.run(main())
'
```

The index plan follows current repository queries: case expiry/token lookup,
case-scoped children, facilities, source manifests, prices, service bundles,
assistance, glossary, and CMS/regional benchmarks. A unique
`source_manifest_id + row_hash` index is not created because those fields do
not exist in the current model; inventing the index would not enforce the
existing deterministic price key.

Before production, inspect `cases` for a legacy `cases_expires_at_ttl` index.
Do not leave a parent-only TTL in place: Atlas could delete the case before
the application removes bill lines, analyses, packets, and receipts. The
current plan uses a normal `cases_expires_at` lookup index and expects
`scripts/purge_expired_cases.py` to run on a schedule for cascade-safe expiry.
Index initialization never drops the legacy index automatically; review and
remove it explicitly on the confirmed Atlas target.

## Read-only inventory

```bash
uv run python -m scripts.mongo_inventory --redact
```

This writes `../artifacts/mongo_inventory.json`. It contains safe metadata
only: database/collection names, counts, safe index definitions, TTLs,
synthetic and source-status counts, active-market counts, orphan/missing-
provenance counts, duplicate-group counts, and classification. It never
contains document bodies, raw IDs, filenames, OCR text, source URLs, signed
query strings, credentials, or the MongoDB URI.

## Cleanup dry-run (default)

```bash
uv run python -m scripts.mongo_cleanup --dry-run
```

The command performs no writes and creates:

- `../artifacts/mongo_inventory.json` — redacted metadata inventory.
- `../artifacts/mongo_cleanup_plan.md` — reviewable counts, reasons, exact
  filters, target fingerprint, and rollback description.
- `../artifacts/mongo_cleanup_manifest.private.json` — exact document IDs;
  mode `0600` and gitignored.

Only synthetic public price records with no existing lifecycle/cleanup fields
are proposed, and only for reversible quarantine. Unknown collections,
duplicates, inactive sources, private cases, real MRF rows, CMS reference
data, the two P0 facilities, and `nrv_core_v1` remain review-only/preserved.
Permanent deletion is not implemented.

## Reviewed quarantine apply

Do not run apply during integration review. After a human reviews the plan,
confirms the exact Atlas target, and confirms a recovery path, the deliberately
verbose command is:

```bash
MONGODB_CLEANUP_WRITES_ENABLED=true \
uv run python -m scripts.mongo_cleanup \
  --apply \
  --plan-id <reviewed-plan-id> \
  --confirm-target <target-id> \
  --acknowledge-reviewed-plan \
  --backup-confirmed \
  --allow-remote-write
```

Apply rejects an altered manifest, a different target, or any count/ID-set
change since dry-run. It sets `active=false`, `status=quarantined`, a controlled
reason, `cleanup_run_id`, and a BSON UTC timestamp. It never deletes.

Rollback uses the exact cleanup run ID and the same target/write gates:

```bash
MONGODB_CLEANUP_WRITES_ENABLED=true \
uv run python -m scripts.mongo_cleanup \
  --rollback <cleanup-run-id> \
  --confirm-target <target-id> \
  --acknowledge-reviewed-plan \
  --backup-confirmed \
  --allow-remote-write
```

For expired/private cases, continue to use
`scripts/purge_expired_cases.py`; the generic cleanup tool never selects
private case documents.
