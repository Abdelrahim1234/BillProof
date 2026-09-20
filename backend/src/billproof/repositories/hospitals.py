from billproof.config import get_settings
from billproof.models import Facility, FacilityAssistance, FacilitySource


def active_market_filter() -> dict:
    """The canonical predicate for facilities visible to runtime clients."""
    return {"name": {"$in": get_settings().active_market_facility_list}}


async def count_hospitals(db) -> int:
    return await db["facilities"].count_documents(active_market_filter())


async def all_facility_ids(db) -> list[str]:
    docs = await db["facilities"].find(active_market_filter()).to_list()
    return [d["_id"] for d in docs]


async def get_active_facility(db, facility_id: str) -> Facility | None:
    doc = await db["facilities"].find_one({"_id": facility_id, **active_market_filter()})
    return Facility.from_doc(doc) if doc else None


async def get_facility(db, facility_id: str) -> Facility | None:
    doc = await db["facilities"].find_one({"_id": facility_id})
    return Facility.from_doc(doc) if doc else None


async def get_facility_by_name(db, name: str) -> Facility | None:
    doc = await db["facilities"].find_one({"name": name})
    return Facility.from_doc(doc) if doc else None


async def search_facilities(
    db,
    *,
    name: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    limit: int = 25,
) -> list[Facility]:
    flt: dict = {}
    if name:
        flt["name"] = {"$regex": name, "$options": "i"}
    if city:
        flt["city"] = {"$regex": city, "$options": "i"}
    if state:
        flt["state"] = state.upper()
    if zip_code:
        flt["zip_code"] = zip_code
    docs = await db["facilities"].find(flt).limit(limit).to_list()
    return [Facility.from_doc(d) for d in docs]


async def search_active_facilities(
    db,
    *,
    name: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    limit: int = 25,
) -> list[Facility]:
    matching_names = get_settings().active_market_facility_list
    if name:
        matching_names = [candidate for candidate in matching_names if name.casefold() in candidate.casefold()]
    flt: dict = {"name": {"$in": matching_names}}
    if city:
        flt["city"] = {"$regex": city, "$options": "i"}
    if state:
        flt["state"] = state.upper()
    if zip_code:
        flt["zip_code"] = zip_code
    docs = await db["facilities"].find(flt).limit(limit).to_list()
    return [Facility.from_doc(d) for d in docs]


async def find_by_name_query(db, query: str, state: str | None, limit: int = 10) -> list[Facility]:
    matching_names = [
        name for name in get_settings().active_market_facility_list if query.casefold() in name.casefold()
    ]
    flt: dict = {"name": {"$in": matching_names}}
    if state:
        flt["state"] = state.upper()
    docs = await db["facilities"].find(flt).limit(limit).to_list()
    return [Facility.from_doc(d) for d in docs]


async def get_assistance(db, facility_id: str) -> list[FacilityAssistance]:
    docs = await db["facility_assistance"].find({"facility_id": facility_id}).to_list()
    return [FacilityAssistance.from_doc(d) for d in docs]


async def facilities_by_type(db, facility_type: str) -> list[Facility]:
    docs = await db["facilities"].find({"facility_type": facility_type}).to_list()
    return [Facility.from_doc(d) for d in docs]


async def upsert_facility(db, facility: Facility) -> None:
    await db["facilities"].update_one({"_id": facility.id}, {"$set": facility.to_set()}, upsert=True)


async def get_facility_source(
    db, hospital_id: str, *, source_url: str | None = None, sha256: str | None = None
) -> FacilitySource | None:
    flt: dict = {"hospital_id": hospital_id}
    if source_url:
        flt["source_url"] = source_url
    if sha256:
        flt["sha256"] = sha256
    doc = await db["hospital_sources"].find_one(flt)
    return FacilitySource.from_doc(doc) if doc else None


async def upsert_facility_source(db, source: FacilitySource) -> None:
    await db["hospital_sources"].update_one({"_id": source.id}, {"$set": source.to_set()}, upsert=True)


async def sources_by_type(db, source_types: set[str]) -> list[FacilitySource]:
    docs = await db["hospital_sources"].find({"source_type": {"$in": sorted(source_types)}}).to_list()
    return [FacilitySource.from_doc(d) for d in docs]


async def delete_sources_matching_url_fragment(db, fragment: str) -> int:
    docs = await db["hospital_sources"].find({}).to_list()
    removed = 0
    for d in docs:
        if fragment in d.get("source_url", ""):
            await db["hospital_sources"].delete_one({"_id": d["_id"]})
            removed += 1
    return removed
