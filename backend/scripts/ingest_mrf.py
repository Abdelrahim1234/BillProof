"""Admin CLI: ingest a CMS-format MRF (V3 JSON or tall CSV) into price_records.

Never invoked from a request path (docs/02: "Never download a large file
during an API or MCP request"). Streams JSON with ijson so a real multi-GB MRF
does not need to fit in memory.

Usage:
    uv run python scripts/ingest_mrf.py --file data/fixtures/cms_v3_small.json \
        --hospital-name "LewisGale Hospital Montgomery" --source-type cms_mrf \
        --synthetic --source-url https://example.invalid/cms-hpt.json
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import ijson
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from billproof.db import SessionLocal, init_db
from billproof.enums import ChargeType
from billproof.models import Facility, FacilitySource, PriceRecord
from billproof.services.code_normalizer import normalize_code, normalize_payer

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ALLOWLIST = REPO_ROOT / "data" / "seed" / "code_allowlist.json"
PROVENANCE_LOG = Path(
    os.environ.get("BILLPROOF_PROVENANCE_LOG", REPO_ROOT / "data" / "seed" / "ingest_history.json")
)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_allowlist(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    entries = json.loads(path.read_text())
    return {(e["code_type"], e["code"]) for e in entries}


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def iter_json_rows(path: Path):
    """Yields normalized row dicts from a CMS V3-shaped MRF JSON, streamed."""
    with path.open("rb") as fh:
        for item in ijson.items(fh, "standard_charge_information.item"):
            description = item.get("description")
            codes = item.get("code_information") or []
            if not codes:
                continue
            code_raw = codes[0].get("code")
            declared_type = codes[0].get("type")
            for charge in item.get("standard_charges") or []:
                setting = charge.get("setting", "unknown")
                base = {
                    "description": description,
                    "code_raw": code_raw,
                    "declared_type": declared_type,
                    "setting": setting,
                }
                if charge.get("gross_charge") is not None:
                    yield {**base, "charge_type": ChargeType.GROSS.value, "amount": charge["gross_charge"]}
                if charge.get("discounted_cash") is not None:
                    yield {
                        **base,
                        "charge_type": ChargeType.DISCOUNTED_CASH.value,
                        "amount": charge["discounted_cash"],
                    }
                if charge.get("deidentified_minimum") is not None:
                    yield {
                        **base,
                        "charge_type": ChargeType.DEIDENTIFIED_MIN.value,
                        "amount": charge["deidentified_minimum"],
                    }
                if charge.get("deidentified_maximum") is not None:
                    yield {
                        **base,
                        "charge_type": ChargeType.DEIDENTIFIED_MAX.value,
                        "amount": charge["deidentified_maximum"],
                    }
                allowed = charge.get("allowed_amounts") or {}
                count = allowed.get("count")
                for key, ctype in (
                    ("p10", ChargeType.ALLOWED_P10.value),
                    ("median", ChargeType.ALLOWED_MEDIAN.value),
                    ("p90", ChargeType.ALLOWED_P90.value),
                ):
                    if allowed.get(key) is not None:
                        yield {**base, "charge_type": ctype, "amount": allowed[key], "allowed_count": count}
                for payer in charge.get("payers_information") or []:
                    if payer.get("standard_charge_dollar") is not None:
                        yield {
                            **base,
                            "charge_type": ChargeType.PAYER_NEGOTIATED.value,
                            "amount": payer["standard_charge_dollar"],
                            "payer_name": payer.get("payer_name"),
                            "plan_name": payer.get("plan_name"),
                            "charge_scope": payer.get("billing_class"),
                        }


def iter_csv_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("amount"):
                continue
            yield {
                "description": row.get("description"),
                "code_raw": row.get("code"),
                "declared_type": row.get("code_type"),
                "setting": row.get("setting", "unknown"),
                "charge_type": row.get("charge_type"),
                "amount": row.get("amount"),
                "payer_name": row.get("payer_name") or None,
                "plan_name": row.get("plan_name") or None,
                "charge_scope": row.get("charge_scope") or None,
                "allowed_count": row.get("allowed_count") or None,
                "source_url": row.get("source_url") or None,
                "file_date": row.get("file_date") or None,
                "source_record_locator": row.get("source_record_locator") or None,
            }


def get_or_create_facility(db: Session, name: str) -> Facility:
    facility = db.scalar(select(Facility).where(Facility.name == name))
    if not facility:
        raise SystemExit(f"No seeded facility named {name!r}. Run scripts/seed.py first (facility identity).")
    return facility


def record_provenance(entry: dict) -> None:
    log = []
    if PROVENANCE_LOG.exists():
        log = json.loads(PROVENANCE_LOG.read_text())
    log.append(entry)
    PROVENANCE_LOG.write_text(json.dumps(log, indent=2, default=str))


def ingest(
    db: Session,
    *,
    file_path: Path,
    hospital_name: str,
    source_type: str,
    synthetic: bool,
    source_url: str,
    file_date: date | None = None,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
) -> int:
    facility = get_or_create_facility(db, hospital_name)
    allowlist = load_allowlist(allowlist_path)
    checksum = sha256_of(file_path)
    retrieved_at = datetime.utcnow()

    rows = iter_json_rows(file_path) if file_path.suffix == ".json" else iter_csv_rows(file_path)

    inserted = 0
    for row in rows:
        normalized = normalize_code(row["code_raw"], row.get("declared_type"))
        if allowlist and (normalized.code_type, normalized.code) not in allowlist:
            continue
        amount = _to_decimal(row.get("amount"))
        if amount is None or amount <= 0:
            continue
        record = PriceRecord(
            hospital_id=facility.id,
            code_type=normalized.code_type,
            code=normalized.code,
            modifier=normalized.modifier,
            description=row.get("description"),
            care_setting=row.get("setting") or "unknown",
            charge_scope=row.get("charge_scope") or "unknown",
            charge_type=row["charge_type"],
            payer_name=row.get("payer_name"),
            payer_normalized=normalize_payer(row.get("payer_name")),
            plan_name=row.get("plan_name"),
            plan_normalized=normalize_payer(row.get("plan_name")),
            amount=amount,
            allowed_count=int(row["allowed_count"]) if row.get("allowed_count") else None,
            mrf_date=file_date,
            source_url=row.get("source_url") or source_url,
            source_record_locator=row.get("source_record_locator"),
            is_synthetic=synthetic,
        )
        db.add(record)
        inserted += 1
    db.flush()

    existing_source = db.scalar(
        select(FacilitySource).where(
            FacilitySource.hospital_id == facility.id, FacilitySource.sha256 == checksum
        )
    )
    if not existing_source:
        db.add(
            FacilitySource(
                hospital_id=facility.id,
                source_type=source_type,
                source_url=source_url,
                file_date=file_date,
                retrieved_at=retrieved_at,
                sha256=checksum,
                active=True,
            )
        )
    db.commit()

    record_provenance(
        {
            "file": str(file_path.relative_to(REPO_ROOT)),
            "hospital_name": hospital_name,
            "source_type": source_type,
            "source_url": source_url,
            "sha256": checksum,
            "retrieved_at": retrieved_at.isoformat(),
            "is_synthetic": synthetic,
            "rows_ingested": inserted,
        }
    )
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--hospital-name", required=True)
    parser.add_argument("--source-type", default="cms_mrf")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--file-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        file_date = date.fromisoformat(args.file_date) if args.file_date else None
        count = ingest(
            db,
            file_path=args.file,
            hospital_name=args.hospital_name,
            source_type=args.source_type,
            synthetic=args.synthetic,
            source_url=args.source_url,
            file_date=file_date,
            allowlist_path=args.allowlist,
        )
        print(f"Ingested {count} price rows from {args.file} for {args.hospital_name}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
