"""CLAUDE_FINAL_DEMO_HARDENING_PROMPT Section 6: purge_case_cascade must
delete the parent case document, every child record, and verify zero remain
-- idempotently, without leaking cross-case existence, and without touching
shared reference data.

This app has no separate object/blob storage (uploads are already deleted in
a `finally` block before persistence -- see services/extraction.py) and no
background job system (every write is synchronous within one request), so
"uploaded/temporary objects absent" and "concurrent job cannot commit after
the fence" are structurally satisfied rather than separately tested here --
see the module docstring in services/case_purge.py.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from billproof import store
from billproof.models import (
    ActivityReceipt,
    Analysis,
    BillLine,
    Case,
    CaseEvidence,
    Facility,
    Packet,
    PriceRecord,
    ScreenSubmission,
)
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo
from billproof.services.case_purge import CASE_SCOPED_COLLECTIONS, purge_case


async def _seeded_case(db, private_db) -> Case:
    case = Case(
        access_token_hash="x" * 64,
        coverage_type="uninsured",
        language="en",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    await private_db["cases"].insert_one(case.to_doc())

    line = BillLine(case_id=case.id, code="71046", code_type="CPT", billed_amount=Decimal("100.00"))
    await private_db["bill_lines"].insert_one(line.to_doc())
    analysis = Analysis(case_id=case.id, input_hash="h", status="completed", result_json={})
    await private_db["analyses"].insert_one(analysis.to_doc())
    packet = Packet(case_id=case.id, goal="billing_review", language="en", packet_json={}, markdown="x")
    await private_db["packets"].insert_one(packet.to_doc())
    receipt = ActivityReceipt(
        case_id=case.id, transport="rest", tool_name="x", display_name="x", status="success", summary="x"
    )
    await private_db["activity_receipts"].insert_one(receipt.to_doc())
    evidence = CaseEvidence(case_id=case.id, facility_id="fac-1", confidence="high", snapshot_json={})
    await private_db["case_evidence"].insert_one(evidence.to_doc())
    screen = ScreenSubmission(
        case_id=case.id,
        room_code="test-room",
        source_label="own_bill",
        coverage_type="uninsured",
        analysis_json={},
        lines_json=[],
        expires_at=case.expires_at,
    )
    await private_db["screen_submissions"].insert_one(screen.to_doc())
    return case


async def _counts_for_case(private_db, case_id: str) -> dict[str, int]:
    counts = {c: await private_db[c].count_documents({"case_id": case_id}) for c in CASE_SCOPED_COLLECTIONS}
    counts["cases"] = 1 if await private_db["cases"].find_one({"_id": case_id}) else 0
    return counts


async def test_purge_case_cascade_removes_parent_children_and_bytes(client):
    private_db = store.get_private_db()
    case = await _seeded_case(store.get_public_db(), private_db)

    before = await _counts_for_case(private_db, case.id)
    # plan_benefit_profiles has no writer anywhere in the app yet (grep
    # confirms it) -- it's in the registry for when one exists, not seeded here.
    seeded = {k: v for k, v in before.items() if k != "plan_benefit_profiles"}
    assert all(n > 0 for n in seeded.values()), f"fixture did not seed every collection: {before}"

    await purge_case(private_db, case)

    after = await _counts_for_case(private_db, case.id)
    assert all(n == 0 for n in after.values()), f"records survived purge: {after}"


async def test_purge_case_cascade_is_idempotent(client):
    private_db = store.get_private_db()
    case = await _seeded_case(store.get_public_db(), private_db)

    first = await purge_case(private_db, case)
    assert first["cases"] == 1

    # A fully absent case is a documented idempotent success, not an error.
    second = await purge_case(private_db, case)
    assert second["cases"] == 1
    for collection in CASE_SCOPED_COLLECTIONS:
        assert second[collection] == 0

    after = await _counts_for_case(private_db, case.id)
    assert all(n == 0 for n in after.values())


async def test_purge_case_cascade_tenant_isolation(client):
    """Cross-case delete is denied at the API layer without leaking whether
    the other case exists (docs/06's case-token model is this app's tenant
    boundary -- there is no separate tenant id)."""
    resp_a = client.post("/api/v1/cases", json={"coverage_type": "uninsured"})
    resp_b = client.post("/api/v1/cases", json={"coverage_type": "uninsured"})
    token_a = resp_a.json()["data"]["access_token"]
    case_id_b = resp_b.json()["data"]["case_id"]

    # Case A's token must not delete case B, and the error must not reveal
    # whether case B exists (it's the same "token does not match" response
    # a garbage/nonexistent case_id in the URL would also get).
    denied = client.delete(f"/api/v1/cases/{case_id_b}", headers={"Authorization": f"Bearer {token_a}"})
    assert denied.status_code == 403

    denied_garbage = client.delete(
        "/api/v1/cases/not-a-real-case-id", headers={"Authorization": f"Bearer {token_a}"}
    )
    assert denied_garbage.status_code == denied.status_code == 403
    assert denied.json()["error"]["message"] == denied_garbage.json()["error"]["message"]

    # Case B must still be fully intact.
    still_there = client.get(
        f"/api/v1/cases/{case_id_b}", headers={"Authorization": f"Bearer {resp_b.json()['data']['access_token']}"}
    )
    assert still_there.status_code == 200


async def test_purge_case_cascade_retries_to_completion_after_injected_failure(client, monkeypatch):
    """The fake backend's db[name] returns a fresh collection wrapper on
    every access (it reloads from disk each time -- see store.py), so the
    failure has to be injected at that access point, not on one collection
    instance, to actually land on the call purge_case makes."""
    private_db = store.get_private_db()
    case = await _seeded_case(store.get_public_db(), private_db)

    real_getitem = type(private_db).__getitem__
    injected = {"done": False}

    def flaky_getitem(self, name):
        collection = real_getitem(self, name)
        if name == "packets" and not injected["done"]:
            injected["done"] = True

            async def failing_delete_many(*_args, **_kwargs):
                raise RuntimeError("injected mid-delete failure")

            collection.delete_many = failing_delete_many
        return collection

    monkeypatch.setattr(type(private_db), "__getitem__", flaky_getitem)

    with pytest.raises(RuntimeError, match="injected mid-delete failure"):
        await purge_case(private_db, case)

    # Retry (no code change, no special-cased recovery path) reaches full completion.
    monkeypatch.setattr(type(private_db), "__getitem__", real_getitem)
    result = await purge_case(private_db, case)
    assert result["cases"] == 1

    after = await _counts_for_case(private_db, case.id)
    assert all(n == 0 for n in after.values())


async def test_purge_case_leaves_shared_reference_data_unchanged(client):
    public_db = store.get_public_db()
    private_db = store.get_private_db()

    facility = Facility(name="Purge Test Hospital", facility_type="hospital", address="1 Main St", city="Blacksburg", state="VA", zip_code="24060")
    await hospitals_repo.upsert_facility(public_db, facility)
    price = PriceRecord(
        hospital_id=facility.id, code_type="CPT", code="71046", charge_type="discounted_cash",
        amount=Decimal("100.00"), source_url="https://example.org/mrf.json", is_synthetic=True,
    )
    await prices_repo.upsert(public_db, price)

    case = await _seeded_case(public_db, private_db)
    await purge_case(private_db, case)

    assert await hospitals_repo.get_facility_by_name(public_db, "Purge Test Hospital") is not None
    assert await public_db["price_records"].find_one({"_id": price.id}) is not None


def test_case_purge_registry_is_complete():
    """CLAUDE_FINAL_DEMO_HARDENING_PROMPT Section 6: fails the build if a new
    case_id-carrying model is added to models.py without a matching entry in
    CASE_SCOPED_COLLECTIONS -- introspects the real model definitions, not a
    hand-maintained duplicate list."""
    import inspect

    from billproof import models

    case_scoped_models = {
        name: cls
        for name, cls in vars(models).items()
        if inspect.isclass(cls)
        and issubclass(cls, models.StoredModel)
        and cls is not models.StoredModel
        and cls is not models.Case  # the parent itself, not a child collection
        and "case_id" in cls.model_fields
    }

    registered_models = set(CASE_SCOPED_COLLECTIONS.values())
    missing = {name: cls for name, cls in case_scoped_models.items() if cls not in registered_models}
    assert not missing, (
        f"models with a case_id field are missing from CASE_SCOPED_COLLECTIONS "
        f"in services/case_purge.py: {list(missing)} -- add them or purge_case_cascade "
        f"will silently leave their rows behind after a delete"
    )
