"""Build a redacted metadata-only inventory for BillBuster storage."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from billproof import store
from billproof.config import get_settings

SCHEMA_VERSION = 1

KEEP_REQUIRED = "KEEP_REQUIRED"
KEEP_SHARED_REFERENCE = "KEEP_SHARED_REFERENCE"
KEEP_PRIVATE_CASE_DATA = "KEEP_PRIVATE_CASE_DATA"
UNKNOWN_REQUIRES_REVIEW = "UNKNOWN_REQUIRES_REVIEW"

PUBLIC_CLASSIFICATIONS = {
    "facilities": KEEP_REQUIRED,
    "markets": KEEP_REQUIRED,
    "hospital_sources": KEEP_REQUIRED,
    "source_manifests": KEEP_REQUIRED,
    "price_records": KEEP_REQUIRED,
    "medicare_benchmarks": KEEP_SHARED_REFERENCE,
    "regional_benchmarks": KEEP_SHARED_REFERENCE,
    "service_bundles": KEEP_SHARED_REFERENCE,
    "facility_assistance": KEEP_SHARED_REFERENCE,
    "billing_glossary": KEEP_SHARED_REFERENCE,
}

PRIVATE_COLLECTIONS = {
    "cases",
    "bill_lines",
    "analyses",
    "packets",
    "activity_receipts",
    "case_evidence",
    "plan_benefit_profiles",
    "uploads",
    "documents",
    "extraction",
    "coverage_snapshots",
    "comparisons",
    "chats",
    "jobs",
    "deletion_state",
}

CASE_CHILD_COLLECTIONS = PRIVATE_COLLECTIONS - {"cases"}
LEGACY_NAME_PATTERN = re.compile(
    r"(?:^|[_-])(legacy|old|backup|archive|test|demo|tmp)(?:$|[_-])",
    re.IGNORECASE,
)


def _fingerprint(values: list[Any]) -> str:
    normalized = "\n".join(sorted(str(value) for value in values))
    return sha256(normalized.encode()).hexdigest()


def _classification(database_role: str, collection: str) -> str:
    if database_role == "public":
        return PUBLIC_CLASSIFICATIONS.get(collection, UNKNOWN_REQUIRES_REVIEW)
    if collection in PRIVATE_COLLECTIONS:
        return KEEP_PRIVATE_CASE_DATA
    return UNKNOWN_REQUIRES_REVIEW


def _legacy_indicators(collection: str) -> list[str]:
    return sorted({match.group(1).lower() for match in LEGACY_NAME_PATTERN.finditer(collection)})


def _safe_index_report(indexes: dict[str, dict]) -> list[dict]:
    report: list[dict] = []
    for name, definition in sorted(indexes.items()):
        keys = definition.get("key", [])
        if hasattr(keys, "items"):
            keys = list(keys.items())
        item = {
            "name": str(name),
            "keys": [[str(key), direction] for key, direction in keys],
            "unique": bool(definition.get("unique", False)),
            "sparse": bool(definition.get("sparse", False)),
            "ttl_seconds": definition.get("expireAfterSeconds"),
        }
        report.append(item)
    return report


async def _storage_size(db, collection: str) -> int | None:
    if store.backend_name() != "mongodb":
        return None
    try:
        stats = await db.command({"collStats": collection, "scale": 1})
    except Exception:  # noqa: BLE001 -- optional metadata must not abort inventory
        return None
    size = stats.get("storageSize")
    return int(size) if isinstance(size, int | float) else None


async def _collection_report(database_role: str, db, collection: str) -> dict:
    coll = db[collection]
    count = await coll.count_documents({})
    ids = await coll.distinct("_id")
    try:
        index_info = await coll.index_information()
    except Exception:  # noqa: BLE001 -- read-only Atlas roles may omit index metadata
        index_info = {}
    report = {
        "name": collection,
        "classification": _classification(database_role, collection),
        "document_count": count,
        "document_id_fingerprint": _fingerprint(ids),
        "storage_size_bytes": await _storage_size(db, collection),
        "indexes": _safe_index_report(index_info),
        "legacy_test_demo_name_indicators": _legacy_indicators(collection),
    }
    if collection == "price_records":
        report["synthetic_counts"] = {
            "true": await coll.count_documents({"is_synthetic": True}),
            "false": await coll.count_documents({"is_synthetic": False}),
            "absent": await coll.count_documents({"is_synthetic": {"$exists": False}}),
        }
    if collection in {"hospital_sources", "source_manifests"}:
        report["active_counts"] = {
            "true": await coll.count_documents({"active": True}),
            "false": await coll.count_documents({"active": False}),
            "absent": await coll.count_documents({"active": {"$exists": False}}),
        }
    return report


async def _orphan_report(public_db, private_db, public_names: set[str], private_names: set[str]) -> dict:
    report: dict[str, int | None] = {
        "price_records_missing_facility": None,
        "hospital_sources_missing_facility": None,
    }
    if "facilities" in public_names:
        facility_ids = {str(value) for value in await public_db["facilities"].distinct("_id")}
        for collection, key in (
            ("price_records", "price_records_missing_facility"),
            ("hospital_sources", "hospital_sources_missing_facility"),
        ):
            if collection not in public_names:
                continue
            referenced_ids = await public_db[collection].distinct("hospital_id")
            orphan_ids = [value for value in referenced_ids if str(value) not in facility_ids]
            report[key] = sum(
                [await public_db[collection].count_documents({"hospital_id": value}) for value in orphan_ids],
                start=0,
            )

    case_ids = (
        {str(value) for value in await private_db["cases"].distinct("_id")}
        if "cases" in private_names
        else set()
    )
    for collection in sorted(CASE_CHILD_COLLECTIONS & private_names):
        referenced_ids = await private_db[collection].distinct("case_id")
        orphan_ids = [value for value in referenced_ids if str(value) not in case_ids]
        report[f"{collection}_missing_case"] = sum(
            [await private_db[collection].count_documents({"case_id": value}) for value in orphan_ids],
            start=0,
        )
    return report


async def _missing_provenance(public_db, public_names: set[str]) -> dict[str, int]:
    requirements = {
        "price_records": (
            "hospital_id",
            "source_type",
            "source_url",
            "citation_url",
            "source_record_locator",
        ),
        "hospital_sources": ("hospital_id", "source_type", "source_url", "sha256", "retrieved_at"),
        "source_manifests": ("source_type", "source_url", "sha256", "retrieved_at"),
    }
    report: dict[str, int] = {}
    for collection, fields in requirements.items():
        if collection not in public_names:
            continue
        projection = {field: 1 for field in fields}
        projection["_id"] = 0
        docs = await public_db[collection].find({}, projection).to_list(length=None)
        report[collection] = sum(1 for doc in docs if any(not doc.get(field) for field in fields))
    return report


async def _duplicate_report(public_db, public_names: set[str]) -> dict[str, dict[str, int]]:
    keys_by_collection = {
        "hospital_sources": ("hospital_id", "sha256"),
        "source_manifests": ("source_type", "facility_id", "sha256"),
        "price_records": (
            "hospital_id",
            "source_url",
            "source_record_locator",
            "charge_type",
        ),
    }
    report: dict[str, dict[str, int]] = {}
    for collection, fields in keys_by_collection.items():
        if collection not in public_names:
            continue
        projection = {field: 1 for field in fields}
        projection["_id"] = 1
        groups: dict[tuple[str, ...], list[Any]] = defaultdict(list)
        docs = await public_db[collection].find({}, projection).to_list(length=None)
        for doc in docs:
            key = tuple(str(doc.get(field, "")) for field in fields)
            if all(key):
                groups[key].append(doc.get("_id"))
        duplicates = [ids for ids in groups.values() if len(ids) > 1]
        report[collection] = {
            "duplicate_groups": len(duplicates),
            "duplicate_excess_documents": sum(len(ids) - 1 for ids in duplicates),
        }
    return report


async def build_inventory() -> dict:
    """Return safe metadata only; no document bodies or raw identifiers."""
    settings = get_settings()
    public_db = store.get_public_db()
    private_db = store.get_private_db()
    public_names = set(await public_db.list_collection_names())
    private_names = set(await private_db.list_collection_names())

    databases: list[dict] = []
    for role, db, names in (
        ("public", public_db, public_names),
        ("private", private_db, private_names),
    ):
        collections = [await _collection_report(role, db, name) for name in sorted(names)]
        databases.append(
            {
                "role": role,
                "name": store.logical_database_names()[role],
                "collections": collections,
            }
        )

    active_names = settings.active_market_facility_list
    active_facility_count = (
        await public_db["facilities"].count_documents({"name": {"$in": active_names}})
        if "facilities" in public_names
        else 0
    )
    unknown = [
        {"database": database["role"], "collection": collection["name"]}
        for database in databases
        for collection in database["collections"]
        if collection["classification"] == UNKNOWN_REQUIRES_REVIEW
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "redacted": True,
        "target": {
            "backend": store.backend_name(),
            "target_id": store.target_id(),
            "databases": store.logical_database_names(),
        },
        "active_market": {
            "market_id": settings.active_market_id,
            "configured_facility_count": len(active_names),
            "matching_facility_count": active_facility_count,
        },
        "databases": databases,
        "orphan_reference_counts": await _orphan_report(
            public_db,
            private_db,
            public_names,
            private_names,
        ),
        "missing_required_provenance_counts": await _missing_provenance(public_db, public_names),
        "deterministic_duplicate_counts": await _duplicate_report(public_db, public_names),
        "unknown_collections_requiring_review": unknown,
        "notes": [
            "No document bodies, raw document identifiers, filenames, OCR text, URLs, or credentials are included.",
            "A null storage size means the selected backend cannot safely expose collStats.",
            "Duplicate counts are informational; no duplicate is a cleanup candidate without review.",
        ],
    }


def write_inventory(inventory: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
