"""Seed facility identity, service bundles, and verified demo price data.

Run: uv run python scripts/seed.py

The checked-in price snapshot is a small, manually verified extract from the
official hospital MRFs. The multi-hundred-megabyte source files are deliberately
not stored in the repository; data/seed/provenance.json records their hashes and
retrieval metadata instead. Synthetic parser fixtures are never loaded here.
"""

import csv
import json
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select

from billproof.db import Base, SessionLocal, engine, init_db
from billproof.enums import CareSetting, ChargeScope, ChargeType, CodeType
from billproof.models import Facility, FacilitySource, PriceRecord, ServiceBundle
from billproof.services.code_normalizer import normalize_code, normalize_payer

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = REPO_ROOT / "data" / "seed"
PROVENANCE_PATH = SEED_DIR / "provenance.json"
CURATED_SOURCE_TYPE = "cms_mrf_verified_extract"
CURATED_SOURCE_TYPES = {CURATED_SOURCE_TYPE, "cms_mrf_verified"}

VERIFIED_PRICE_COLUMNS = {
    "source_id",
    "hospital_name",
    "description",
    "code",
    "code_type",
    "setting",
    "charge_scope",
    "charge_type",
    "payer_name",
    "plan_name",
    "amount",
    "currency",
    "rate_unit",
    "rate_method",
    "allowed_count",
    "source_url",
    "file_date",
    "source_record_locator",
}


def seed_facilities(db) -> None:
    hospitals = json.loads((SEED_DIR / "hospitals.json").read_text())
    for h in hospitals:
        existing = db.scalar(select(Facility).where(Facility.name == h["name"]))
        if existing:
            continue
        db.add(
            Facility(
                facility_id=h.get("facility_id"),
                organization_npi=h.get("organization_npi"),
                name=h["name"],
                facility_type=h["facility_type"],
                address=h["address"],
                city=h["city"],
                state=h["state"],
                zip_code=h["zip_code"],
                hospital_type=h.get("hospital_type"),
                ownership=h.get("ownership"),
                phone=h.get("phone"),
                latitude=h.get("latitude"),
                longitude=h.get("longitude"),
                financial_assistance_url=h.get("financial_assistance_url"),
                billing_url=h.get("billing_url"),
                public_price_url=h.get("public_price_url"),
                verification_source=h.get("verification_source"),
                verification_date=date.fromisoformat(h["verification_date"])
                if h.get("verification_date")
                else None,
            )
        )
    db.commit()


def seed_urgent_care(db) -> None:
    """Seed locations only; no unverified urgent-care prices are invented."""
    locations = json.loads((SEED_DIR / "urgent_care.json").read_text())
    for loc in locations:
        existing = db.scalar(select(Facility).where(Facility.name == loc["name"]))
        if existing:
            continue
        facility = Facility(
            name=loc["name"],
            facility_type=loc["facility_type"],
            address=loc["address"],
            city=loc["city"],
            state=loc["state"],
            zip_code=loc["zip_code"],
            phone=loc.get("phone"),
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
            public_price_url=loc.get("public_price_url"),
            verification_source=loc.get("verification_source"),
            verification_date=date.fromisoformat(loc["verification_date"])
            if loc.get("verification_date")
            else None,
        )
        db.add(facility)
    db.commit()


def seed_service_bundles(db) -> None:
    codes = json.loads((SEED_DIR / "code_allowlist.json").read_text())
    for c in codes:
        existing = db.scalar(
            select(ServiceBundle).where(ServiceBundle.normalized_service_key == c["service_key"])
        )
        if existing:
            existing.display_name = c["display_name"]
            existing.code = c["code"]
            existing.code_type = c["code_type"]
            existing.setting = c["setting"]
            # A service bundle describes a code/setting, not a billing entity.
            # The verified source rows do not publish billing class, so claiming
            # a facility scope here would make a match look more specific than
            # its evidence supports.
            existing.charge_scope = "unknown"
        else:
            db.add(
                ServiceBundle(
                    display_name=c["display_name"],
                    normalized_service_key=c["service_key"],
                    code=c["code"],
                    code_type=c["code_type"],
                    setting=c["setting"],
                    charge_scope="unknown",
                )
            )
    db.commit()


def remove_synthetic_seed_data(db) -> int:
    """Remove legacy synthetic seed rows before loading the verified snapshot."""
    synthetic_prices = list(db.scalars(select(PriceRecord).where(PriceRecord.is_synthetic.is_(True))))
    for record in synthetic_prices:
        db.delete(record)
    stale_sources = list(
        db.scalars(select(FacilitySource).where(FacilitySource.source_url.contains("example.invalid")))
    )
    for source in stale_sources:
        db.delete(source)
    db.commit()
    return len(synthetic_prices)


def _parse_utc(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("Provenance retrieved_at must be an ISO-8601 UTC timestamp ending in Z")
    return datetime.fromisoformat(value).replace(tzinfo=None)


def _load_provenance() -> dict[str, dict]:
    entries = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("data/seed/provenance.json must contain at least one verified source")

    by_id: dict[str, dict] = {}
    required = {
        "source_id",
        "hospital_name",
        "source_type",
        "source_url",
        "file_date",
        "retrieved_at",
        "schema_version",
        "sha256",
    }
    for entry in entries:
        missing = required - set(entry)
        if missing:
            raise RuntimeError(f"Provenance entry is missing columns: {sorted(missing)}")
        source_id = entry["source_id"]
        if source_id in by_id:
            raise RuntimeError(f"Duplicate provenance source_id: {source_id}")
        if len(entry["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in entry["sha256"]):
            raise RuntimeError(f"Invalid SHA-256 for provenance source {source_id}")
        if entry["source_type"] != CURATED_SOURCE_TYPE:
            raise RuntimeError(
                f"Provenance source {source_id} must use source_type {CURATED_SOURCE_TYPE!r}"
            )
        date.fromisoformat(entry["file_date"])
        _parse_utc(entry["retrieved_at"])
        by_id[source_id] = entry
    return by_id


def _validated_price_rows() -> tuple[list[dict], dict[str, dict]]:
    path = SEED_DIR / "public_prices.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing_columns = VERIFIED_PRICE_COLUMNS - set(reader.fieldnames or [])
        if missing_columns:
            raise RuntimeError(f"public_prices.csv is missing columns: {sorted(missing_columns)}")
        rows = list(reader)
    if not rows:
        raise RuntimeError("public_prices.csv has no verified rows; refusing to seed synthetic prices")

    provenance = _load_provenance()
    allowlist = {
        (entry["code_type"], entry["code"])
        for entry in json.loads((SEED_DIR / "code_allowlist.json").read_text(encoding="utf-8"))
    }
    valid_code_types = {item.value for item in CodeType}
    valid_settings = {item.value for item in CareSetting}
    valid_scopes = {item.value for item in ChargeScope}
    valid_charge_types = {item.value for item in ChargeType}

    seen_row_keys: set[tuple[str, str, str, str]] = set()
    for line_number, row in enumerate(rows, start=2):
        source = provenance.get(row["source_id"])
        if not source:
            raise RuntimeError(f"CSV row {line_number} references unknown source_id {row['source_id']!r}")
        if row["hospital_name"] != source["hospital_name"]:
            raise RuntimeError(f"CSV row {line_number} hospital does not match its provenance entry")
        if row["source_url"] != source["source_url"] or row["file_date"] != source["file_date"]:
            raise RuntimeError(f"CSV row {line_number} source URL/date does not match provenance")
        if row["code_type"] not in valid_code_types or row["setting"] not in valid_settings:
            raise RuntimeError(f"CSV row {line_number} has an invalid code type or setting")
        if row["charge_scope"] not in valid_scopes or row["charge_type"] not in valid_charge_types:
            raise RuntimeError(f"CSV row {line_number} has an invalid scope or charge type")
        normalized = normalize_code(row["code"], row["code_type"])
        if (normalized.code_type, normalized.code) not in allowlist:
            raise RuntimeError(f"CSV row {line_number} is not in code_allowlist.json")
        try:
            amount = Decimal(row["amount"])
        except InvalidOperation as exc:
            raise RuntimeError(f"CSV row {line_number} has an invalid amount") from exc
        if amount <= 0:
            raise RuntimeError(f"CSV row {line_number} amount must be positive")
        if not row["source_record_locator"]:
            raise RuntimeError(f"CSV row {line_number} has no source record locator")
        row_key = (
            row["hospital_name"],
            row["source_url"],
            row["source_record_locator"],
            row["charge_type"],
        )
        if row_key in seen_row_keys:
            raise RuntimeError(f"CSV row {line_number} duplicates a curated price key")
        seen_row_keys.add(row_key)

    return rows, provenance


def _price_values(row: dict, facility: Facility, source: dict) -> dict:
    normalized = normalize_code(row["code"], row["code_type"])
    return {
        "hospital_id": facility.id,
        "code_type": normalized.code_type,
        "code": normalized.code,
        "modifier": normalized.modifier,
        "description": row["description"] or None,
        "care_setting": row["setting"],
        "charge_scope": row["charge_scope"],
        "charge_type": row["charge_type"],
        "payer_name": row["payer_name"] or None,
        "payer_normalized": normalize_payer(row["payer_name"]),
        "plan_name": row["plan_name"] or None,
        "plan_normalized": normalize_payer(row["plan_name"]),
        "amount": Decimal(row["amount"]),
        "currency": row["currency"] or "USD",
        "rate_unit": row["rate_unit"] or None,
        "rate_method": row["rate_method"] or None,
        "allowed_count": int(row["allowed_count"]) if row["allowed_count"] else None,
        "mrf_date": date.fromisoformat(row["file_date"]),
        "source_url": row["source_url"],
        "source_record_locator": row["source_record_locator"],
        "is_synthetic": False,
        "created_at": _parse_utc(source["retrieved_at"]),
    }


def seed_verified_prices(db) -> int:
    """Reconcile the authoritative curated snapshot and original-file provenance.

    Ownership is limited to sources registered with a curated source type. Rows
    from manual or other ingestion sources are deliberately outside this
    reconciliation and remain untouched.
    """
    rows, provenance = _validated_price_rows()

    facilities = {
        facility.name: facility
        for facility in db.scalars(select(Facility).where(Facility.facility_type == "hospital"))
    }
    existing_curated_sources = list(
        db.scalars(select(FacilitySource).where(FacilitySource.source_type.in_(CURATED_SOURCE_TYPES)))
    )
    owned_source_keys = {
        (source.hospital_id, source.source_url) for source in existing_curated_sources
    }
    sources_by_key: dict[tuple[str, str], list[FacilitySource]] = {}
    for source in existing_curated_sources:
        sources_by_key.setdefault((source.hospital_id, source.source_url), []).append(source)

    desired_source_keys: set[tuple[str, str]] = set()
    for source in provenance.values():
        facility = facilities.get(source["hospital_name"])
        if not facility:
            raise RuntimeError(f"No seeded facility named {source['hospital_name']!r}")
        source_key = (facility.id, source["source_url"])
        desired_source_keys.add(source_key)
        owned_source_keys.add(source_key)
        matches = sources_by_key.get(source_key, [])
        existing_source = matches[0] if matches else None
        if existing_source is None:
            existing_source = FacilitySource(hospital_id=facility.id, source_url=source["source_url"])
            db.add(existing_source)
        existing_source.source_type = source["source_type"]
        existing_source.schema_version = source["schema_version"]
        existing_source.file_date = date.fromisoformat(source["file_date"])
        existing_source.retrieved_at = _parse_utc(source["retrieved_at"])
        existing_source.sha256 = source["sha256"]
        existing_source.active = True
        for duplicate in matches[1:]:
            db.delete(duplicate)

    for source_key, matches in sources_by_key.items():
        if source_key not in desired_source_keys:
            for stale_source in matches:
                stale_source.active = False

    desired_prices: dict[tuple[str, str, str, str], tuple[dict, Facility, dict]] = {}
    for row in rows:
        facility = facilities[row["hospital_name"]]
        key = (
            facility.id,
            row["source_url"],
            row["source_record_locator"],
            row["charge_type"],
        )
        desired_prices[key] = (row, facility, provenance[row["source_id"]])

    existing_prices_by_key: dict[tuple[str, str, str, str], list[PriceRecord]] = {}
    non_synthetic_prices = db.scalars(
        select(PriceRecord).where(PriceRecord.is_synthetic.is_(False))
    )
    for price in non_synthetic_prices:
        if (price.hospital_id, price.source_url) not in owned_source_keys:
            continue
        key = (
            price.hospital_id,
            price.source_url,
            price.source_record_locator or "",
            price.charge_type,
        )
        existing_prices_by_key.setdefault(key, []).append(price)

    for key, (row, facility, source) in desired_prices.items():
        matches = existing_prices_by_key.pop(key, [])
        price = matches[0] if matches else PriceRecord()
        for field, value in _price_values(row, facility, source).items():
            setattr(price, field, value)
        if not matches:
            db.add(price)
        for duplicate in matches[1:]:
            db.delete(duplicate)

    for stale_prices in existing_prices_by_key.values():
        for stale_price in stale_prices:
            db.delete(stale_price)

    db.commit()
    return len(rows)


def main() -> None:
    Base.metadata.create_all(bind=engine)
    init_db()
    db = SessionLocal()
    try:
        seed_facilities(db)
        seed_urgent_care(db)
        seed_service_bundles(db)

        removed_synthetic_rows = remove_synthetic_seed_data(db)
        verified_rows = seed_verified_prices(db)
        remaining_synthetic_rows = list(
            db.scalars(select(PriceRecord.id).where(PriceRecord.is_synthetic.is_(True)))
        )
        if remaining_synthetic_rows:
            raise RuntimeError("Synthetic price rows remain after verified seeding")

        print(f"Seeded facilities and {len(json.loads((SEED_DIR / 'code_allowlist.json').read_text()))} service bundles.")
        print(f"Loaded {verified_rows} verified price rows from {len(_load_provenance())} official MRFs.")
        if removed_synthetic_rows:
            print(f"Removed {removed_synthetic_rows} legacy synthetic price rows.")
        print(f"Synthetic price rows in database: {len(remaining_synthetic_rows)}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
