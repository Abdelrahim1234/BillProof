import json

import pytest

from billproof import store
from billproof.admin.mongo_cleanup import (
    CleanupSafetyError,
    apply_manifest,
    build_cleanup_manifest,
    rollback_cleanup,
    validate_apply_confirmation,
    write_cleanup_artifacts,
)
from billproof.admin.mongo_inventory import build_inventory


async def _seed_inventory_shape() -> None:
    public = store.get_public_db()
    private = store.get_private_db()
    await public["facilities"].insert_one(
        {
            "_id": "facility-1",
            "name": "LewisGale Hospital Montgomery",
            "private_note": "PATIENT_BODY_MUST_NOT_APPEAR",
        }
    )
    provenance = {
        "hospital_id": "facility-1",
        "source_type": "cms_mrf_verified_extract",
        "source_url": "https://hospital.example/mrf.csv",
        "citation_url": "https://hospital.example/pricing",
        "source_record_locator": "row:1",
    }
    await public["price_records"].insert_one(
        {"_id": "synthetic-1", "is_synthetic": True, "charge_type": "gross", **provenance}
    )
    await public["price_records"].insert_one(
        {"_id": "real-1", "is_synthetic": False, "charge_type": "gross", **provenance}
    )
    await public["hospital_sources"].insert_one(
        {
            "_id": "source-1",
            "hospital_id": "facility-1",
            "source_type": "cms_mrf_verified_extract",
            "source_url": "https://hospital.example/mrf.csv",
            "sha256": "a" * 64,
            "retrieved_at": "2026-09-20T00:00:00+00:00",
            "active": True,
        }
    )
    await private["cases"].insert_one({"_id": "case-1", "expires_at": "2026-09-21T00:00:00+00:00"})
    await private["bill_lines"].insert_one({"_id": "line-1", "case_id": "case-1"})
    await private["legacy_dump"].insert_one({"_id": "unknown-1"})


async def test_inventory_is_metadata_only_and_classifies_unknowns() -> None:
    await _seed_inventory_shape()
    inventory = await build_inventory()
    serialized = json.dumps(inventory)

    assert "PATIENT_BODY_MUST_NOT_APPEAR" not in serialized
    assert "synthetic-1" not in serialized
    assert "hospital.example" not in serialized
    assert inventory["active_market"]["matching_facility_count"] == 1
    assert inventory["orphan_reference_counts"]["bill_lines_missing_case"] == 0
    assert inventory["unknown_collections_requiring_review"] == [
        {"database": "private", "collection": "legacy_dump"}
    ]
    price_report = next(
        collection
        for database in inventory["databases"]
        if database["role"] == "public"
        for collection in database["collections"]
        if collection["name"] == "price_records"
    )
    assert price_report["synthetic_counts"] == {"true": 1, "false": 1, "absent": 0}


async def test_cleanup_artifacts_separate_exact_ids_and_plan_is_deterministic(tmp_path) -> None:
    await _seed_inventory_shape()
    inventory = await build_inventory()
    first = await build_cleanup_manifest(inventory)
    second = await build_cleanup_manifest(inventory)

    assert first["plan_id"] == second["plan_id"]
    inventory_path = tmp_path / "mongo_inventory.json"
    plan_path = tmp_path / "mongo_cleanup_plan.md"
    manifest_path = tmp_path / "mongo_cleanup_manifest.private.json"
    write_cleanup_artifacts(
        inventory,
        first,
        inventory_path=inventory_path,
        plan_path=plan_path,
        manifest_path=manifest_path,
    )

    assert "synthetic-1" not in inventory_path.read_text()
    assert "synthetic-1" not in plan_path.read_text()
    assert "synthetic-1" in manifest_path.read_text()
    assert manifest_path.stat().st_mode & 0o777 == 0o600
    assert "Permanent deletion: not implemented" in plan_path.read_text()


async def test_cleanup_quarantine_and_rollback_are_reversible() -> None:
    await _seed_inventory_shape()
    inventory = await build_inventory()
    manifest = await build_cleanup_manifest(inventory)

    result = await apply_manifest(manifest)
    assert result["actions"] == [{"collection": "price_records", "quarantined_count": 1}]
    synthetic = await store.get_public_db()["price_records"].find_one({"_id": "synthetic-1"})
    real = await store.get_public_db()["price_records"].find_one({"_id": "real-1"})
    assert synthetic["status"] == "quarantined"
    assert synthetic["active"] is False
    assert "status" not in real

    rollback = await rollback_cleanup(manifest["plan_id"])
    assert rollback["restored_count"] == 1
    restored = await store.get_public_db()["price_records"].find_one({"_id": "synthetic-1"})
    for field in ("active", "status", "quarantine_reason", "cleanup_run_id", "quarantined_at"):
        assert field not in restored


async def test_cleanup_rejects_a_stale_plan_before_writes() -> None:
    await _seed_inventory_shape()
    manifest = await build_cleanup_manifest(await build_inventory())
    await store.get_public_db()["price_records"].insert_one(
        {"_id": "synthetic-2", "is_synthetic": True}
    )

    with pytest.raises(CleanupSafetyError, match="stale"):
        await apply_manifest(manifest)
    assert await store.get_public_db()["price_records"].count_documents({"status": "quarantined"}) == 0


async def test_apply_confirmation_requires_every_gate() -> None:
    await _seed_inventory_shape()
    manifest = await build_cleanup_manifest(await build_inventory())

    with pytest.raises(CleanupSafetyError, match="acknowledgement"):
        validate_apply_confirmation(
            manifest,
            reviewed_plan_id=manifest["plan_id"],
            confirmed_target_id=store.target_id(),
            acknowledged_review=False,
            backup_confirmed=True,
            allow_remote_write=False,
            remote_writes_enabled=False,
        )
