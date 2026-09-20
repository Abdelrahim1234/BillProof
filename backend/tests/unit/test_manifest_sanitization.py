"""CLAUDE_FINAL_DEMO_HARDENING_PROMPT Fix 2: retrieval URLs must never leak a
signed access credential into storage, an API response, or a log."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from billproof import store
from billproof.models import Facility, PriceRecord
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo
from billproof.services.privacy import (
    citation_for_price_record,
    contains_sas_params,
    find_sas_leak,
    strip_query,
)

# A fake-but-realistic SAS-signed URL -- exactly the shape this project's own
# real ingestion produced, never a real credential.
_FAKE_SIGNED_URL = (
    "https://example.blob.core.windows.net/mrf/lewisgale.json"
    "?si=fake-access-policy&spr=https&sv=2026-02-06&sr=c&sig=NOT-A-REAL-SIGNATURE%3D"
)


def test_strip_query_removes_sas_parameters():
    resolved = strip_query(_FAKE_SIGNED_URL)
    assert resolved == "https://example.blob.core.windows.net/mrf/lewisgale.json"
    assert not contains_sas_params(resolved)
    assert contains_sas_params(_FAKE_SIGNED_URL)


def test_recursive_leak_scan_finds_a_signed_url_at_any_depth():
    clean = {"a": [1, 2, {"b": "https://example.com/no-query"}]}
    assert find_sas_leak(clean) is None

    leaked = {"a": [1, 2, {"b": _FAKE_SIGNED_URL}]}
    assert find_sas_leak(leaked) == "$.a[2].b"


def test_citation_for_price_record_never_exposes_a_signed_url():
    """Even if a signed URL somehow reached storage unsanitized, the public
    citation must never surface it."""
    record = PriceRecord(
        hospital_id="hosp-1",
        code_type="CPT",
        code="71046",
        charge_type="discounted_cash",
        amount=Decimal("100.00"),
        source_url=_FAKE_SIGNED_URL,  # deliberately unsanitized, to prove the citation layer catches it
        is_synthetic=True,
    )
    citation = citation_for_price_record(record)
    assert not contains_sas_params(citation.source_url)
    assert find_sas_leak(citation.model_dump(mode="json")) is None

    # A dirty citation page must not bypass the same response boundary.
    record.citation_url = _FAKE_SIGNED_URL
    citation = citation_for_price_record(record)
    assert not contains_sas_params(citation.source_url)
    assert find_sas_leak(citation.model_dump(mode="json")) is None


async def test_manifest_sanitizer_dry_run_and_apply():
    from sanitize_manifests import scan_and_fix

    db = store.get_public_db()
    facility = Facility(
        name="Sanitizer Test Hospital", facility_type="hospital", address="1 Main St", city="Blacksburg",
        state="VA", zip_code="24060", public_price_url="https://example.org/pricing",
    )
    await hospitals_repo.upsert_facility(db, facility)
    dirty = PriceRecord(
        hospital_id=facility.id,
        code_type="CPT",
        code="71046",
        charge_type="discounted_cash",
        amount=Decimal("100.00"),
        source_url=_FAKE_SIGNED_URL,
        is_synthetic=True,
        mrf_date=date.today(),
    )
    await prices_repo.upsert(db, dirty)

    dry_run_report = await scan_and_fix(db, apply=False)
    assert dry_run_report["price_records_by_facility"].get("Sanitizer Test Hospital", 0) >= 1

    # Dry run must not have modified anything.
    still_dirty = [
        PriceRecord.from_doc(doc)
        for doc in await db["price_records"].find({"hospital_id": facility.id, "code": "71046"}).to_list()
    ]
    assert any(contains_sas_params(r.source_url) for r in still_dirty)

    apply_report = await scan_and_fix(db, apply=True)
    assert apply_report["price_records_by_facility"].get("Sanitizer Test Hospital", 0) >= 1

    fixed = [
        PriceRecord.from_doc(doc)
        for doc in await db["price_records"].find({"hospital_id": facility.id, "code": "71046"}).to_list()
    ]
    assert all(not contains_sas_params(r.source_url) for r in fixed)
    assert all(r.citation_url == "https://example.org/pricing" for r in fixed)

    # Idempotent: a second apply run finds nothing left to fix.
    second_report = await scan_and_fix(db, apply=True)
    assert second_report["price_records_by_facility"].get("Sanitizer Test Hospital", 0) == 0
