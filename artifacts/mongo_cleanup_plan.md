# MongoDB cleanup plan

- Plan ID: `b42fd3747cc80e92ac331ca2`
- Target fingerprint: `db4314cd20b755f126c1`
- Backend: `file`
- Mode: dry-run; no writes were performed
- Supported apply action: reversible quarantine only
- Permanent deletion: not implemented

## Proposed action

| Database | Collection | Exact filter | Expected count | ID-set fingerprint | Reason |
| --- | --- | --- | ---: | --- | --- |
| `public` | `price_records` | `{"active": {"$exists": false}, "cleanup_run_id": {"$exists": false}, "is_synthetic": true, "status": {"$exists": false}}` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `synthetic_public_price_evidence` |

Applying this reviewed plan marks only the exact matched rows with `active=false`, `status=quarantined`, a controlled reason, the plan ID, and a BSON/UTC timestamp. It does not delete documents.

## Stale-plan and target protection

Apply rejects a different target fingerprint, altered manifest, plan-ID mismatch, or any change to the exact matching ID set/count. Remote writes also require both a server-side environment gate and explicit CLI confirmation. The connection URI is never written to an artifact.

## Rollback

Rollback is keyed by cleanup run ID (the plan ID): `b42fd3747cc80e92ac331ca2`. It removes only the quarantine metadata written by this tool from rows carrying that exact ID. Because candidates must not already have those metadata fields, rollback restores their prior shape.

## Review-only findings

- Unknown collections requiring human review: 0. They are never auto-selected.
- Duplicate metadata groups: `{"hospital_sources": {"duplicate_excess_documents": 0, "duplicate_groups": 0}, "price_records": {"duplicate_excess_documents": 0, "duplicate_groups": 0}}`. No duplicates are auto-selected because surviving-record choice requires provenance review.
- Inactive sources, orphan references, expired cases, and legacy/test/demo name indicators are inventory findings only; use the authorized case-purge workflow for private cases.

## Protected data

The active `nrv_core_v1` facilities, non-synthetic MRF rows, active source manifests, and CMS/reference collections have no proposed mutation. Unknown collections are preserved.
