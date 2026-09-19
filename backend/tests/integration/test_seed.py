import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from billproof.db import SessionLocal
from billproof.models import Facility, FacilitySource, PriceRecord, ServiceBundle

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


def test_seed_script_populates_expected_rows(client):
    result = _run_seed()
    assert "Loaded 21 verified price rows from 2 official MRFs" in result.stdout
    assert "Synthetic price rows in database: 0" in result.stdout

    db = SessionLocal()
    try:
        facilities = list(db.scalars(select(Facility)))
        names = {f.name for f in facilities}
        assert {
            "LewisGale Hospital Montgomery",
            "Carilion New River Valley Medical Center",
        }.issubset(names)
        assert sum(1 for f in facilities if f.facility_type == "urgent_care") == 3
        assert any(f.facility_type == "urgent_care" and f.public_price_url is None for f in facilities)

        bundles = list(db.scalars(select(ServiceBundle)))
        assert len(bundles) == 8
        assert all(bundle.charge_scope == "unknown" for bundle in bundles)

        prices = list(db.scalars(select(PriceRecord)))
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

        sources = list(db.scalars(select(FacilitySource)))
        assert len(sources) == 2
        assert {s.schema_version for s in sources} == {"3.0.0"}
        assert {s.sha256 for s in sources} == {
            "a275b2d66ad697bebf47391c1130a1c123cadf2b49ec8e5696de919c9155767c",
            "48f6c44e51424a14cf3418eb54bc1e4aacce3f7bd3c7db78e73a9adf34981e3d",
        }
    finally:
        db.close()

    _run_seed()
    db = SessionLocal()
    try:
        assert len(list(db.scalars(select(PriceRecord)))) == 21
        assert len(list(db.scalars(select(FacilitySource)))) == 2
    finally:
        db.close()


def test_seed_reconciles_stale_curated_data_without_touching_other_real_data(client):
    _run_seed()

    db = SessionLocal()
    try:
        lewisgale = db.scalar(
            select(Facility).where(Facility.name == "LewisGale Hospital Montgomery")
        )
        xray = db.scalar(
            select(PriceRecord).where(
                PriceRecord.hospital_id == lewisgale.id,
                PriceRecord.code == "71046",
                PriceRecord.charge_type == "discounted_cash",
            )
        )
        current_source = db.scalar(
            select(FacilitySource).where(
                FacilitySource.hospital_id == lewisgale.id,
                FacilitySource.source_url == xray.source_url,
            )
        )

        # Simulate a prior snapshot whose values and source metadata have drifted.
        xray.amount = Decimal("1.23")
        xray.description = "STALE DESCRIPTION"
        current_source.sha256 = "0" * 64
        current_source.schema_version = "old"
        db.add(
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
            )
        )
        db.add(
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
            )
        )

        old_source_url = "https://old-seed.example/lewisgale-standardcharges.json"
        db.add(
            FacilitySource(
                hospital_id=lewisgale.id,
                source_type="cms_mrf_verified_extract",
                source_url=old_source_url,
                schema_version="2.0.0",
                file_date=date(2025, 1, 1),
                retrieved_at=datetime.now(UTC).replace(tzinfo=None),
                sha256="1" * 64,
                active=True,
            )
        )
        db.add(
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
            )
        )

        user_source_url = "https://prices.example.org/user-import.csv"
        user_source = FacilitySource(
            hospital_id=lewisgale.id,
            source_type="manual_import",
            source_url=user_source_url,
            schema_version="1",
            file_date=date(2026, 1, 1),
            retrieved_at=datetime.now(UTC).replace(tzinfo=None),
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
        db.add_all([user_source, user_price])

        bundle = db.scalar(select(ServiceBundle).limit(1))
        bundle.charge_scope = "facility"
        lewisgale_id = lewisgale.id
        xray_locator = xray.source_record_locator
        db.commit()
        user_price_id = user_price.id
        user_source_id = user_source.id
    finally:
        db.close()

    _run_seed()

    db = SessionLocal()
    try:
        refreshed_xrays = list(
            db.scalars(
                select(PriceRecord).where(
                    PriceRecord.hospital_id == lewisgale_id,
                    PriceRecord.code == "71046",
                    PriceRecord.charge_type == "discounted_cash",
                    PriceRecord.source_record_locator == xray_locator,
                )
            )
        )
        assert len(refreshed_xrays) == 1
        refreshed_xray = refreshed_xrays[0]
        assert refreshed_xray.amount == Decimal("1187.00")
        assert refreshed_xray.description == "CHEST XRAY 2 V"
        assert not db.scalar(
            select(PriceRecord).where(PriceRecord.source_record_locator == "stale curated locator")
        )
        assert not db.scalar(select(PriceRecord).where(PriceRecord.source_url == old_source_url))

        retired_source = db.scalar(
            select(FacilitySource).where(FacilitySource.source_url == old_source_url)
        )
        assert retired_source.active is False
        restored_source = db.scalar(
            select(FacilitySource).where(
                FacilitySource.hospital_id == lewisgale_id,
                FacilitySource.source_url == refreshed_xray.source_url,
            )
        )
        assert restored_source.sha256 == (
            "a275b2d66ad697bebf47391c1130a1c123cadf2b49ec8e5696de919c9155767c"
        )
        assert restored_source.schema_version == "3.0.0"

        assert db.get(PriceRecord, user_price_id).amount == Decimal("88.88")
        assert db.get(FacilitySource, user_source_id).active is True
        assert all(
            bundle.charge_scope == "unknown" for bundle in db.scalars(select(ServiceBundle))
        )
        assert len(list(db.scalars(select(PriceRecord)))) == 22
    finally:
        db.close()
