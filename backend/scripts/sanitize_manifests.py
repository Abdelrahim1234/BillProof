"""Admin CLI: strip query strings from persisted retrieval URLs and backfill
citation_url. CLAUDE_FINAL_DEMO_HARDENING_PROMPT Fix 2.

A real MRF source URL (Azure Blob storage, this project's own experience) can
carry a SAS signature -- a live, time-limited access credential -- in its
query string. That must never be persisted. Dry-run first; this never prints
a discovered secret, only counts.

Does not drop or clear any collection: existing documents are updated in
place, never deleted.

Usage:
    uv run python scripts/sanitize_manifests.py             # dry run, reports only
    uv run python scripts/sanitize_manifests.py --apply      # writes the sanitized values
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from billproof import store
from billproof.models import Facility, FacilitySource
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo
from billproof.services.privacy import contains_sas_params, strip_query


def _needs_fix(source_url: str | None, citation_url: str | None) -> bool:
    return bool(contains_sas_params(source_url)) or not citation_url


async def scan_and_fix(db, *, apply: bool) -> dict:
    facility_docs = await db["facilities"].find({}).to_list()
    facilities = {f.id: f for f in (Facility.from_doc(d) for d in facility_docs)}

    affected_by_facility: dict[str, int] = {}

    all_prices = await prices_repo.all_synthetic(db) + await prices_repo.all_non_synthetic(db)
    for record in all_prices:
        if not _needs_fix(record.source_url, record.citation_url):
            continue
        name = facilities.get(record.hospital_id).name if record.hospital_id in facilities else record.hospital_id
        affected_by_facility[name] = affected_by_facility.get(name, 0) + 1
        if apply:
            facility = facilities.get(record.hospital_id)
            updated = record.model_copy(
                update={
                    "source_url": strip_query(record.source_url),
                    "citation_url": record.citation_url or (facility.public_price_url if facility else None),
                }
            )
            await prices_repo.upsert(db, updated)

    source_docs = await db["hospital_sources"].find({}).to_list()
    affected_sources = 0
    for doc in source_docs:
        source = FacilitySource.from_doc(doc)
        if not _needs_fix(source.source_url, source.citation_url):
            continue
        affected_sources += 1
        if apply:
            facility = facilities.get(source.hospital_id)
            updated = source.model_copy(
                update={
                    "source_url": strip_query(source.source_url),
                    "citation_url": source.citation_url or (facility.public_price_url if facility else None),
                }
            )
            await hospitals_repo.upsert_facility_source(db, updated)

    return {
        "price_records_affected": sum(affected_by_facility.values()),
        "price_records_by_facility": affected_by_facility,
        "facility_sources_affected": affected_sources,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write the sanitized values. Default is dry-run.")
    args = parser.parse_args()

    await store.connect()
    db = store.get_public_db()
    report = await scan_and_fix(db, apply=args.apply)
    await store.close()

    verb = "Sanitized" if args.apply else "Would sanitize (dry run)"
    print(f"{verb} {report['price_records_affected']} price record(s):")
    for name, count in sorted(report["price_records_by_facility"].items()):
        print(f"  {name}: {count}")
    print(f"{verb} {report['facility_sources_affected']} facility source document(s).")
    if not args.apply and (report["price_records_affected"] or report["facility_sources_affected"]):
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(main())
