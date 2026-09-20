import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from billproof import store
from billproof.models import Facility, FacilitySource, PriceRecord, ServiceBundle
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_seed():
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "seed.py")],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result


async def _all(collection: str, model) -> list:
    docs = await store.get_public_db()[collection].find({}).to_list()
    return [model.from_doc(d) for d in docs]


async def test_seed_script_populates_expected_rows(client):
    result = _run_seed()
    assert "Loaded 21 verified price rows from 2 official MRFs" in result.stdout
    assert "Synthetic price rows in database: 0" in result.stdout

    facilities = await _all("facilities", Facility)
    names = {f.name for f in facilities}
    assert {
        "LewisGale Hospital Montgomery",
        "Carilion New River Valley Medical Center",
    }.issubset(names)
    assert sum(1 for f in facilities if f.facility_type == "urgent_care") == 3
    assert any(f.facility_type == "urgent_care" and f.public_price_url is None for f in facilities)

    bundles = await _all("service_bundles", ServiceBundle)
    assert len(bundles) == 8
    assert all(bundle.charge_scope == "unknown" for bundle in bundles)

    prices = await _all("price_records", PriceRecord)
    assert len(prices) == 21
    assert all(not p.is_synthetic for p in prices)
    assert all("example.invalid" not in p.source_url for p in prices)
    assert all(p.source_record_locator for p in prices)

    lewisgale = next(f for f in facilities if f.name == "LewisGale Hospital Montgomery")
    xray = [
        p
        for p in prices
        if p.code == "71046" and p.charge_type == "discounted_cash" and p.hospital_id == lewisgale.id
    ]
    assert len(xray) == 1
    assert xray[0].amount == Decimal("1187.00")
    assert xray[0].mrf_date == date(2026, 9, 1)

    carilion = next(f for f in facilities if f.name == "Carilion New River Valley Medical Center")
    peer_xray = [
        p
        for p in prices
        if p.code == "71046" and p.charge_type == "discounted_cash" and p.hospital_id == carilion.id
    ]
    assert len(peer_xray) == 1
    assert peer_xray[0].amount == Decimal("145.25")

    sources = await _all("hospital_sources", FacilitySource)
    assert len(sources) == 2
    assert {s.schema_version for s in sources} == {"3.0.0"}
    assert {s.sha256 for s in sources} == {
        "a275b2d66ad697bebf47391c1130a1c123cadf2b49ec8e5696de919c9155767c",
        "48f6c44e51424a14cf3418eb54bc1e4aacce3f7bd3c7db78e73a9adf34981e3d",
    }

    _run_seed()
    assert len(await _all("price_records", PriceRecord)) == 21
    assert len(await _all("hospital_sources", FacilitySource)) == 2


async def test_seed_reconciles_stale_curated_data_without_touching_other_real_data(client):
    _run_seed()
    db = store.get_public_db()

    lewisgale = await hospitals_repo.get_facility_by_name(db, "LewisGale Hospital Montgomery")
    xrays = await prices_repo.search_prices(
        db, hospital_id=lewisgale.id, code="71046", charge_type="discounted_cash", limit=1
    )
    xray = xrays[0]
    current_source = await hospitals_repo.get_facility_source(db, lewisgale.id, source_url=xray.source_url)

    # Simulate a prior snapshot whose values and source metadata have drifted.
    await prices_repo.upsert(db, xray.model_copy(update={"amount": Decimal("1.23"), "description": "STALE DESCRIPTION"}))
    await hospitals_repo.upsert_facility_source(
        db, current_source.model_copy(update={"sha256": "0" * 64, "schema_version": "old"})
    )

    await prices_repo.upsert(
        db,
        PriceRecord(
            hospital_id=lewisgale.id,
            code_type="CPT",
            code="71046",
            description="Removed curated row",
            care_setting="outpatient",
            charge_scope="unknown",
            charge_type="discounted_cash",
            amount=Decimal("2.34"),
            source_url=xray.source_url,
            source_record_locator="stale curated locator",
            is_synthetic=False,
        ),
    )
    await prices_repo.upsert(
        db,
        PriceRecord(
            hospital_id=lewisgale.id,
            code_type=xray.code_type,
            code=xray.code,
            description="Duplicate copy from an older seed run",
            care_setting=xray.care_setting,
            charge_scope=xray.charge_scope,
            charge_type=xray.charge_type,
            amount=Decimal("3.45"),
            source_url=xray.source_url,
            source_record_locator=xray.source_record_locator,
            is_synthetic=False,
        ),
    )

    old_source_url = "https://old-seed.example/lewisgale-standardcharges.json"
    await hospitals_repo.upsert_facility_source(
        db,
        FacilitySource(
            hospital_id=lewisgale.id,
            source_type="cms_mrf_verified_extract",
            source_url=old_source_url,
            schema_version="2.0.0",
            file_date=date(2025, 1, 1),
            retrieved_at=datetime.now(UTC),
            sha256="1" * 64,
            active=True,
        ),
    )
    await prices_repo.upsert(
        db,
        PriceRecord(
            hospital_id=lewisgale.id,
            code_type="CPT",
            code="99999",
            description="Row from retired curated source",
            care_setting="outpatient",
            charge_scope="unknown",
            charge_type="gross",
            amount=Decimal("9.99"),
            source_url=old_source_url,
            source_record_locator="old curated locator",
            is_synthetic=False,
        ),
    )

    user_source_url = "https://prices.example.org/user-import.csv"
    user_source = FacilitySource(
        hospital_id=lewisgale.id,
        source_type="manual_import",
        source_url=user_source_url,
        schema_version="1",
        file_date=date(2026, 1, 1),
        retrieved_at=datetime.now(UTC),
        sha256="2" * 64,
        active=True,
    )
    user_price = PriceRecord(
        hospital_id=lewisgale.id,
        code_type="LOCAL",
        code="USER1",
        description="Unrelated user-ingested real row",
        care_setting="unknown",
        charge_scope="unknown",
        charge_type="gross",
        amount=Decimal("88.88"),
        source_url=user_source_url,
        source_record_locator="manual row 1",
        is_synthetic=False,
    )
    await hospitals_repo.upsert_facility_source(db, user_source)
    await prices_repo.upsert(db, user_price)

    bundles = await _all("service_bundles", ServiceBundle)
    await db["service_bundles"].update_one({"_id": bundles[0].id}, {"$set": {"charge_scope": "facility"}})

    lewisgale_id = lewisgale.id
    xray_locator = xray.source_record_locator
    user_price_id = user_price.id
    user_source_id = user_source.id

    _run_seed()

    refreshed_xrays = await prices_repo.search_prices(
        db, hospital_id=lewisgale_id, code="71046", charge_type="discounted_cash", limit=100
    )
    refreshed_xrays = [p for p in refreshed_xrays if p.source_record_locator == xray_locator]
    assert len(refreshed_xrays) == 1
    refreshed_xray = refreshed_xrays[0]
    assert refreshed_xray.amount == Decimal("1187.00")
    assert refreshed_xray.description == "CHEST XRAY 2 V"

    all_prices = await _all("price_records", PriceRecord)
    assert not any(p.source_record_locator == "stale curated locator" for p in all_prices)
    assert not any(p.source_url == old_source_url for p in all_prices)

    sources = await _all("hospital_sources", FacilitySource)
    retired_source = next(s for s in sources if s.source_url == old_source_url)
    assert retired_source.active is False
    restored_source = next(
        s for s in sources if s.hospital_id == lewisgale_id and s.source_url == refreshed_xray.source_url
    )
    assert restored_source.sha256 == ("a275b2d66ad697bebf47391c1130a1c123cadf2b49ec8e5696de919c9155767c")
    assert restored_source.schema_version == "3.0.0"

    user_price_doc = await db["price_records"].find_one({"_id": user_price_id})
    assert PriceRecord.from_doc(user_price_doc).amount == Decimal("88.88")
    user_source_doc = await db["hospital_sources"].find_one({"_id": user_source_id})
    assert FacilitySource.from_doc(user_source_doc).active is True

    refreshed_bundles = await _all("service_bundles", ServiceBundle)
    assert all(bundle.charge_scope == "unknown" for bundle in refreshed_bundles)
    assert len(all_prices) == 22
