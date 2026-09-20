from fastapi import APIRouter, Depends

from billproof import store
from billproof.api.dependencies import get_public_db
from billproof.config import get_settings
from billproof.errors import ok
from billproof.repositories.hospitals import all_facility_ids, count_hospitals
from billproof.repositories.prices import search_prices

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health():
    return ok({"status": "ok"})


@router.get("/ready")
async def ready(db=Depends(get_public_db)):
    check = await store.health_check()
    settings = get_settings()
    hospital_count = await count_hospitals(db)
    active_facility_ids = await all_facility_ids(db)
    eligible_price_by_hospital = [
        bool(await search_prices(db, hospital_id=hospital_id, limit=1))
        for hospital_id in active_facility_ids
    ]
    seeded = (
        hospital_count == len(settings.active_market_facility_list)
        and len(active_facility_ids) == hospital_count
        and all(eligible_price_by_hospital)
    )
    return ok(
        {
            "status": check["status"],
            "db": "ok" if check["status"] == "ok" else "degraded",
            "backend": store.backend_name(),
            "market_id": settings.active_market_id,
            "seeded": seeded,
        }
    )
