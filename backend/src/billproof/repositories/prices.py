from billproof.models import PriceRecord
from billproof.repositories import hospitals as hospitals_repo
from billproof.services.privacy import strip_query


async def _eligible_public_records(
    db, records: list[PriceRecord], *, require_active_market: bool
) -> list[PriceRecord]:
    """Filter runtime evidence independently of whatever remains stored."""
    active_hospital_ids = set(await hospitals_repo.all_facility_ids(db)) if require_active_market else None
    source_docs = await db["hospital_sources"].find({"active": True}).to_list()
    active_sources = {
        (source.get("hospital_id"), strip_query(source.get("source_url")))
        for source in source_docs
        if source.get("hospital_id") and source.get("source_url") and source.get("sha256")
    }
    return [
        record
        for record in records
        if record.is_synthetic is False
        and (active_hospital_ids is None or record.hospital_id in active_hospital_ids)
        and bool(record.source_type)
        and bool(record.source_url)
        and bool(record.citation_url)
        and bool(record.source_record_locator)
        and (record.hospital_id, strip_query(record.source_url)) in active_sources
    ]


async def search_prices(
    db,
    *,
    hospital_id: str | None = None,
    code_type: str | None = None,
    code: str | None = None,
    care_setting: str | None = None,
    charge_type: str | None = None,
    payer_normalized: str | None = None,
    plan_normalized: str | None = None,
    limit: int = 50,
) -> list[PriceRecord]:
    flt: dict = {"is_synthetic": False}
    if hospital_id:
        flt["hospital_id"] = hospital_id
    if code_type:
        flt["code_type"] = code_type
    if code:
        flt["code"] = code
    if care_setting:
        flt["care_setting"] = care_setting
    if charge_type:
        flt["charge_type"] = charge_type
    if payer_normalized:
        flt["payer_normalized"] = payer_normalized
    if plan_normalized:
        flt["plan_normalized"] = plan_normalized
    # Apply the response limit after eligibility filtering so stale rows cannot
    # crowd verified evidence out of the result window.
    docs = await db["price_records"].find(flt).to_list()
    records = await _eligible_public_records(
        db, [PriceRecord.from_doc(d) for d in docs], require_active_market=True
    )
    return records[:limit]


async def prices_for_hospital_code(db, hospital_id: str, code_type: str, code: str) -> list[PriceRecord]:
    flt = {
        "hospital_id": hospital_id,
        "code_type": code_type,
        "code": code,
        "amount": {"$ne": None},
        "is_synthetic": False,
    }
    docs = await db["price_records"].find(flt).to_list()
    return await _eligible_public_records(
        db, [PriceRecord.from_doc(d) for d in docs], require_active_market=True
    )


async def prices_for_code_any_hospital(
    db, code_type: str, code: str, exclude_hospital_id: str | None = None
) -> list[PriceRecord]:
    flt: dict = {
        "code_type": code_type,
        "code": code,
        "amount": {"$ne": None},
        "is_synthetic": False,
    }
    docs = await db["price_records"].find(flt).to_list()
    records = await _eligible_public_records(
        db, [PriceRecord.from_doc(d) for d in docs], require_active_market=True
    )
    if exclude_hospital_id:
        records = [r for r in records if r.hospital_id != exclude_hospital_id]
    return records


async def query(
    db,
    hospital_ids: list[str],
    code_type: str,
    code: str,
    *,
    charge_type: str,
    care_setting: str | None = None,
    modifier: str | None = None,
    payer_normalized: str | None = None,
    plan_normalized: str | None = None,
    charge_scope: str | None = None,
) -> list[PriceRecord]:
    """docs/03 match-tier queries (moved out of services/price_matching.py so
    every price query funnels through one repository).

    code_type="CPT_HCPCS" (docs/03: "a five-digit code with no declared
    system stays CPT_HCPCS, never auto-CPT") searches both CPT and HCPCS
    price records for the same code. This is not a cross-code-system guess
    (invariant 7) -- CPT codes ARE HCPCS Level I codes; CPT_HCPCS exists
    because the *bill* didn't declare which label the price source used for
    the identical number, not because the two are being treated as
    equivalent-but-different codes.
    """
    flt: dict = {
        "hospital_id": {"$in": hospital_ids},
        "code_type": {"$in": ["CPT", "HCPCS", "CPT_HCPCS"]} if code_type == "CPT_HCPCS" else code_type,
        "code": code,
        "charge_type": charge_type,
        "is_synthetic": False,
    }
    if care_setting:
        flt["care_setting"] = care_setting
    if modifier is not None:
        flt["modifier"] = modifier
    if payer_normalized:
        flt["payer_normalized"] = payer_normalized
    if plan_normalized:
        flt["plan_normalized"] = plan_normalized
    if charge_scope and charge_scope != "unknown":
        flt["charge_scope"] = charge_scope
    docs = await db["price_records"].find(flt).to_list()
    # amount > 0 filtered in Python: cents comparisons are exact, but keeping
    # the predicate here (rather than as a stored-cents filter op) keeps this
    # function simple and readable.
    # This low-level matcher accepts an explicit hospital ID set so unit-level
    # comparison logic remains market-agnostic. Runtime callers validate the
    # case/facility against the active market before reaching this function;
    # peer IDs come from hospitals_repo.all_facility_ids().
    records = await _eligible_public_records(
        db, [PriceRecord.from_doc(d) for d in docs], require_active_market=False
    )
    return [r for r in records if r.amount and r.amount > 0]


async def get_public_price(db, record_id: str) -> PriceRecord | None:
    doc = await db["price_records"].find_one({"_id": record_id})
    if not doc or doc.get("is_synthetic") is not False:
        return None
    records = await _eligible_public_records(
        db, [PriceRecord.from_doc(doc)], require_active_market=True
    )
    return records[0] if records else None


async def find_exact(
    db, *, hospital_id: str, source_url: str, source_record_locator: str, charge_type: str
) -> PriceRecord | None:
    doc = await db["price_records"].find_one(
        {
            "hospital_id": hospital_id,
            "source_url": source_url,
            "source_record_locator": source_record_locator,
            "charge_type": charge_type,
        }
    )
    return PriceRecord.from_doc(doc) if doc else None


async def upsert(db, record: PriceRecord) -> None:
    await db["price_records"].update_one({"_id": record.id}, {"$set": record.to_set()}, upsert=True)


async def delete(db, record_id: str) -> None:
    await db["price_records"].delete_one({"_id": record_id})


async def all_synthetic(db) -> list[PriceRecord]:
    docs = await db["price_records"].find({"is_synthetic": True}).to_list()
    return [PriceRecord.from_doc(d) for d in docs]


async def all_non_synthetic(db) -> list[PriceRecord]:
    docs = await db["price_records"].find({"is_synthetic": False}).to_list()
    return [PriceRecord.from_doc(d) for d in docs]
