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
import asyncio
import csv
import hashlib
import json
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import ijson

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from billproof import store
from billproof.enums import ChargeType
from billproof.models import Facility, FacilitySource, PriceRecord
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo
from billproof.services.code_normalizer import normalize_code, normalize_payer
from billproof.services.privacy import strip_query

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
    """Yields normalized row dicts from a CMS V3-shaped MRF JSON, streamed.

    Emits one full charge set PER CODE in an item's code_information, not
    just the first. A CMS item routinely lists a revenue/CDM code first and
    the CPT/HCPCS code second (verified against this project's own LewisGale
    file: item code_information == [('306','RC'), ('80053','CPT')]) --
    reading only index 0 silently drops every item where the code a caller
    actually wants is secondary, undercounting real available data on any
    bulk re-ingestion.
    """
    with path.open("rb") as fh:
        for item_idx, item in enumerate(ijson.items(fh, "standard_charge_information.item")):
            description = item.get("description")
            codes = item.get("code_information") or []
            for code_entry in codes:
                code_raw = code_entry.get("code")
                declared_type = code_entry.get("type")
                if not code_raw:
                    continue
                suffix = f"({declared_type} {code_raw})"
                for charge_idx, charge in enumerate(item.get("standard_charges") or []):
                    setting = charge.get("setting", "unknown")
                    prefix = f"/standard_charge_information/{item_idx}/standard_charges/{charge_idx}"
                    base = {"description": description, "code_raw": code_raw, "declared_type": declared_type, "setting": setting}
                    if charge.get("gross_charge") is not None:
                        yield {
                            **base,
                            "charge_type": ChargeType.GROSS.value,
                            "amount": charge["gross_charge"],
                            "source_record_locator": f"{prefix}/gross_charge {suffix}",
                        }
                    if charge.get("discounted_cash") is not None:
                        yield {
                            **base,
                            "charge_type": ChargeType.DISCOUNTED_CASH.value,
                            "amount": charge["discounted_cash"],
                            "source_record_locator": f"{prefix}/discounted_cash {suffix}",
                        }
                    if charge.get("deidentified_minimum") is not None:
                        yield {
                            **base,
                            "charge_type": ChargeType.DEIDENTIFIED_MIN.value,
                            "amount": charge["deidentified_minimum"],
                            "source_record_locator": f"{prefix}/deidentified_minimum {suffix}",
                        }
                    if charge.get("deidentified_maximum") is not None:
                        yield {
                            **base,
                            "charge_type": ChargeType.DEIDENTIFIED_MAX.value,
                            "amount": charge["deidentified_maximum"],
                            "source_record_locator": f"{prefix}/deidentified_maximum {suffix}",
                        }
                    allowed = charge.get("allowed_amounts") or {}
                    count = allowed.get("count")
                    for key, ctype in (
                        ("p10", ChargeType.ALLOWED_P10.value),
                        ("median", ChargeType.ALLOWED_MEDIAN.value),
                        ("p90", ChargeType.ALLOWED_P90.value),
                    ):
                        if allowed.get(key) is not None:
                            yield {
                                **base,
                                "charge_type": ctype,
                                "amount": allowed[key],
                                "allowed_count": count,
                                "source_record_locator": f"{prefix}/allowed_amounts/{key} {suffix}",
                            }
                    for payer_idx, payer in enumerate(charge.get("payers_information") or []):
                        if payer.get("standard_charge_dollar") is not None:
                            yield {
                                **base,
                                "charge_type": ChargeType.PAYER_NEGOTIATED.value,
                                "amount": payer["standard_charge_dollar"],
                                "payer_name": payer.get("payer_name"),
                                "plan_name": payer.get("plan_name"),
                                "charge_scope": payer.get("billing_class"),
                                "source_record_locator": f"{prefix}/payers_information/{payer_idx}/standard_charge_dollar {suffix}",
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


async def get_or_create_facility(db, name: str) -> Facility:
    facility = await hospitals_repo.get_facility_by_name(db, name)
    if not facility:
        raise SystemExit(f"No seeded facility named {name!r}. Run scripts/seed.py first (facility identity).")
    return facility


def record_provenance(entry: dict) -> None:
    log = []
    if PROVENANCE_LOG.exists():
        log = json.loads(PROVENANCE_LOG.read_text())
    log.append(entry)
    PROVENANCE_LOG.write_text(json.dumps(log, indent=2, default=str))


async def ingest(
    db,
    *,
    file_path: Path,
    hospital_name: str,
    source_type: str,
    synthetic: bool,
    source_url: str,
    file_date: date | None = None,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
    dry_run: bool = False,
    content_length: int | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> int:
    facility = await get_or_create_facility(db, hospital_name)
    allowlist = load_allowlist(allowlist_path)
    checksum = sha256_of(file_path)
    retrieved_at = datetime.now(UTC)
    # CLAUDE_FINAL_DEMO_HARDENING Fix 2: the raw signed URL (if any) lives
    # only in this local variable and source_record_locator-adjacent request
    # code, for the duration of this run. Nothing persisted below ever
    # carries a query string.
    resolved_origin = strip_query(source_url)
    citation_url = facility.public_price_url

    rows = iter_json_rows(file_path) if file_path.suffix == ".json" else iter_csv_rows(file_path)

    inserted = 0
    for row in rows:
        normalized = normalize_code(row["code_raw"], row.get("declared_type"))
        if allowlist and (normalized.code_type, normalized.code) not in allowlist:
            continue
        amount = _to_decimal(row.get("amount"))
        if amount is None or amount <= 0:
            continue
        inserted += 1
        if dry_run:
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
            source_url=strip_query(row.get("source_url")) or resolved_origin,
            citation_url=citation_url,
            source_record_locator=row.get("source_record_locator"),
            source_type=source_type,
            is_synthetic=synthetic,
        )
        await prices_repo.upsert(db, record)

    if dry_run:
        return inserted

    existing_source = await hospitals_repo.get_facility_source(db, facility.id, sha256=checksum)
    if not existing_source:
        await hospitals_repo.upsert_facility_source(
            db,
            FacilitySource(
                hospital_id=facility.id,
                source_type=source_type,
                source_url=resolved_origin,
                citation_url=citation_url,
                file_date=file_date,
                retrieved_at=retrieved_at,
                sha256=checksum,
                content_length=content_length,
                etag=etag,
                last_modified=last_modified,
                active=True,
            ),
        )

    try:
        file_repr = str(file_path.relative_to(REPO_ROOT))
    except ValueError:
        file_repr = str(file_path)  # outside the repo (e.g. a scratch download), log the absolute path

    record_provenance(
        {
            "file": file_repr,
            "hospital_name": hospital_name,
            "source_type": source_type,
            "source_url": resolved_origin,  # never the raw signed URL -- see strip_query
            "citation_url": citation_url,
            "sha256": checksum,
            "retrieved_at": retrieved_at.isoformat(),
            "is_synthetic": synthetic,
            "rows_ingested": inserted,
        }
    )
    return inserted


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--hospital-name", required=True)
    parser.add_argument("--source-type", default="cms_mrf")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--file-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--dry-run", action="store_true", help="Parse/validate only; write nothing.")
    parser.add_argument("--content-length", type=int, default=None)
    parser.add_argument("--etag", default=None)
    parser.add_argument("--last-modified", default=None)
    args = parser.parse_args()

    await store.connect()
    db = store.get_public_db()
    file_date = date.fromisoformat(args.file_date) if args.file_date else None
    count = await ingest(
        db,
        file_path=args.file,
        hospital_name=args.hospital_name,
        source_type=args.source_type,
        synthetic=args.synthetic,
        source_url=args.source_url,
        file_date=file_date,
        allowlist_path=args.allowlist,
        dry_run=args.dry_run,
        content_length=args.content_length,
        etag=args.etag,
        last_modified=args.last_modified,
    )
    verb = "Validated" if args.dry_run else "Ingested"
    print(f"{verb} {count} price rows from {args.file} for {args.hospital_name}.")
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
