"""Deterministic, reversible cleanup planning for BillBuster storage.

This integration intentionally supports quarantine only. There is no
permanent-delete operation in this module.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from billproof import store

SCHEMA_VERSION = 1
SYNTHETIC_PRICE_FILTER = {
    "is_synthetic": True,
    "active": {"$exists": False},
    "status": {"$exists": False},
    "cleanup_run_id": {"$exists": False},
}


class CleanupSafetyError(RuntimeError):
    """Raised before a cleanup command can mutate an unverified target."""


def _fingerprint(values: list[Any]) -> str:
    normalized = "\n".join(sorted(str(value) for value in values))
    return sha256(normalized.encode()).hexdigest()


def _canonical_plan_payload(manifest: dict) -> dict:
    return {
        "schema_version": manifest["schema_version"],
        "target": manifest["target"],
        "actions": [
            {
                "database": action["database"],
                "collection": action["collection"],
                "operation": action["operation"],
                "filter": action["filter"],
                "expected_count": action["expected_count"],
                "document_id_fingerprint": action["document_id_fingerprint"],
                "reason": action["reason"],
            }
            for action in manifest["actions"]
        ],
    }


def _plan_id(manifest: dict) -> str:
    payload = json.dumps(_canonical_plan_payload(manifest), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()[:24]


async def build_cleanup_manifest(inventory: dict) -> dict:
    """Build an exact private manifest without changing storage."""
    ids = await store.get_public_db()["price_records"].distinct("_id", SYNTHETIC_PRICE_FILTER)
    normalized_ids = sorted(str(value) for value in ids)
    actions = [
        {
            "database": "public",
            "collection": "price_records",
            "operation": "quarantine",
            "filter": SYNTHETIC_PRICE_FILTER,
            "expected_count": len(normalized_ids),
            "document_id_fingerprint": _fingerprint(normalized_ids),
            # Exact IDs are deliberately confined to the gitignored private
            # manifest. The public markdown plan reports only count/hash.
            "document_ids": normalized_ids,
            "reason": "synthetic_public_price_evidence",
        }
    ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "target": inventory["target"],
        "actions": actions,
        "allowed_operation": "reversible_quarantine_only",
        "permanent_delete_supported": False,
    }
    manifest["plan_id"] = _plan_id(manifest)
    return manifest


def render_cleanup_plan(inventory: dict, manifest: dict) -> str:
    action = manifest["actions"][0]
    unknown = inventory["unknown_collections_requiring_review"]
    duplicate_counts = inventory["deterministic_duplicate_counts"]
    lines = [
        "# MongoDB cleanup plan",
        "",
        f"- Plan ID: `{manifest['plan_id']}`",
        f"- Target fingerprint: `{manifest['target']['target_id']}`",
        f"- Backend: `{manifest['target']['backend']}`",
        "- Mode: dry-run; no writes were performed",
        "- Supported apply action: reversible quarantine only",
        "- Permanent deletion: not implemented",
        "",
        "## Proposed action",
        "",
        "| Database | Collection | Exact filter | Expected count | ID-set fingerprint | Reason |",
        "| --- | --- | --- | ---: | --- | --- |",
        (
            f"| `{action['database']}` | `{action['collection']}` | "
            f"`{json.dumps(action['filter'], sort_keys=True)}` | {action['expected_count']} | "
            f"`{action['document_id_fingerprint']}` | `{action['reason']}` |"
        ),
        "",
        (
            "Applying this reviewed plan marks only the exact matched rows with "
            "`active=false`, `status=quarantined`, a controlled reason, the plan ID, and a "
            "BSON/UTC timestamp. It does not delete documents."
        ),
        "",
        "## Stale-plan and target protection",
        "",
        (
            "Apply rejects a different target fingerprint, altered manifest, plan-ID mismatch, or "
            "any change to the exact matching ID set/count. Remote writes also require both a "
            "server-side environment gate and explicit CLI confirmation. The connection URI is "
            "never written to an artifact."
        ),
        "",
        "## Rollback",
        "",
        (
            f"Rollback is keyed by cleanup run ID (the plan ID): `{manifest['plan_id']}`. It "
            "removes only the quarantine metadata written by this tool from rows carrying that "
            "exact ID. Because candidates must not already have those metadata fields, rollback "
            "restores their prior shape."
        ),
        "",
        "## Review-only findings",
        "",
        f"- Unknown collections requiring human review: {len(unknown)}. They are never auto-selected.",
        (
            f"- Duplicate metadata groups: `{json.dumps(duplicate_counts, sort_keys=True)}`. No "
            "duplicates are auto-selected because surviving-record choice requires provenance review."
        ),
        (
            "- Inactive sources, orphan references, expired cases, and legacy/test/demo name "
            "indicators are inventory findings only; use the authorized case-purge workflow for "
            "private cases."
        ),
        "",
        "## Protected data",
        "",
        (
            "The active `nrv_core_v1` facilities, non-synthetic MRF rows, active source manifests, "
            "and CMS/reference collections have no proposed mutation. Unknown collections are preserved."
        ),
        "",
    ]
    return "\n".join(lines)


def write_cleanup_artifacts(
    inventory: dict,
    manifest: dict,
    *,
    inventory_path: Path,
    plan_path: Path,
    manifest_path: Path,
) -> None:
    from billproof.admin.mongo_inventory import write_inventory

    write_inventory(inventory, inventory_path)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(render_cleanup_plan(inventory, manifest), encoding="utf-8")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o600)


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanupSafetyError("Cleanup manifest is missing or invalid") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CleanupSafetyError("Unsupported cleanup manifest schema")
    if manifest.get("plan_id") != _plan_id(manifest):
        raise CleanupSafetyError("Cleanup manifest or plan ID was altered")
    return manifest


def validate_apply_confirmation(
    manifest: dict,
    *,
    reviewed_plan_id: str,
    confirmed_target_id: str,
    acknowledged_review: bool,
    backup_confirmed: bool,
    allow_remote_write: bool,
    remote_writes_enabled: bool,
) -> None:
    if reviewed_plan_id != manifest["plan_id"]:
        raise CleanupSafetyError("Reviewed plan ID does not match the private manifest")
    if confirmed_target_id != store.target_id() or manifest["target"]["target_id"] != store.target_id():
        raise CleanupSafetyError("Confirmed storage target does not match the connected target")
    if not acknowledged_review:
        raise CleanupSafetyError("Apply requires explicit acknowledgement of the reviewed dry-run")
    if not backup_confirmed:
        raise CleanupSafetyError("Apply requires explicit backup/recovery acknowledgement")
    if store.backend_name() == "mongodb" and not (allow_remote_write and remote_writes_enabled):
        raise CleanupSafetyError(
            "Remote quarantine requires --allow-remote-write and MONGODB_CLEANUP_WRITES_ENABLED=true"
        )


def _validate_action(action: dict) -> None:
    allowed = {
        "database": "public",
        "collection": "price_records",
        "operation": "quarantine",
        "filter": SYNTHETIC_PRICE_FILTER,
        "reason": "synthetic_public_price_evidence",
    }
    if any(action.get(key) != value for key, value in allowed.items()):
        raise CleanupSafetyError("Manifest contains an unsupported cleanup action")
    ids = action.get("document_ids")
    if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
        raise CleanupSafetyError("Manifest document IDs are invalid")
    if action.get("expected_count") != len(ids) or action.get("document_id_fingerprint") != _fingerprint(ids):
        raise CleanupSafetyError("Manifest count or ID fingerprint is invalid")


async def apply_manifest(manifest: dict) -> dict:
    """Apply a validated local/remote quarantine plan with stale checks."""
    if manifest.get("plan_id") != _plan_id(manifest):
        raise CleanupSafetyError("Cleanup manifest or plan ID was altered")
    if manifest["target"]["target_id"] != store.target_id():
        raise CleanupSafetyError("Cleanup manifest targets a different storage deployment")

    collection = store.get_public_db()["price_records"]
    applied: list[dict] = []
    for action in manifest["actions"]:
        _validate_action(action)
        current_ids = sorted(str(value) for value in await collection.distinct("_id", action["filter"]))
        if current_ids != sorted(action["document_ids"]):
            raise CleanupSafetyError("Cleanup plan is stale; rerun the dry-run and review a new plan")

        quarantined_at = datetime.now(UTC)
        for document_id in current_ids:
            await collection.update_one(
                {"_id": document_id, **action["filter"]},
                {
                    "$set": {
                        "active": False,
                        "status": "quarantined",
                        "quarantine_reason": action["reason"],
                        "cleanup_run_id": manifest["plan_id"],
                        "quarantined_at": quarantined_at,
                    }
                },
            )
        verified = await collection.count_documents(
            {"cleanup_run_id": manifest["plan_id"], "status": "quarantined"}
        )
        if verified != len(current_ids):
            raise CleanupSafetyError("Quarantine verification failed; use the plan ID to roll back")
        applied.append({"collection": action["collection"], "quarantined_count": verified})
    return {"cleanup_run_id": manifest["plan_id"], "actions": applied}


async def rollback_cleanup(cleanup_run_id: str) -> dict:
    """Remove quarantine fields written by one exact cleanup run ID."""
    if (
        not cleanup_run_id
        or len(cleanup_run_id) != 24
        or any(character not in "0123456789abcdef" for character in cleanup_run_id)
    ):
        raise CleanupSafetyError("A valid cleanup run ID is required")
    collection = store.get_public_db()["price_records"]
    query = {
        "cleanup_run_id": cleanup_run_id,
        "status": "quarantined",
        "quarantine_reason": "synthetic_public_price_evidence",
    }
    ids = sorted(str(value) for value in await collection.distinct("_id", query))
    for document_id in ids:
        await collection.update_one(
            {"_id": document_id, **query},
            {
                "$unset": {
                    "active": "",
                    "status": "",
                    "quarantine_reason": "",
                    "cleanup_run_id": "",
                    "quarantined_at": "",
                }
            },
        )
    remaining = await collection.count_documents(query)
    if remaining:
        raise CleanupSafetyError("Rollback verification failed")
    return {"cleanup_run_id": cleanup_run_id, "restored_count": len(ids)}
