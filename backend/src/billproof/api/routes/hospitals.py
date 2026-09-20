from fastapi import APIRouter, Depends

from billproof.api.dependencies import get_public_db
from billproof.errors import not_found, ok
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo
from billproof.schemas.facilities import FacilityDetail
from billproof.services.privacy import price_reference, public_facility

router = APIRouter(prefix="/api/v1", tags=["hospitals"])


@router.get("/hospitals")
async def list_hospitals(
    name: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip: str | None = None,
    db=Depends(get_public_db),
):
    rows = await hospitals_repo.search_active_facilities(
        db, name=name, city=city, state=state, zip_code=zip
    )
    return ok([public_facility(r).model_dump(mode="json") for r in rows])


@router.get("/hospitals/{hospital_id}")
async def get_hospital(hospital_id: str, db=Depends(get_public_db)):
    facility = await hospitals_repo.get_active_facility(db, hospital_id)
    if not facility:
        raise not_found("Hospital")
    return ok(
        FacilityDetail(**public_facility(facility).model_dump(mode="python")).model_dump(mode="json")
    )


@router.get("/prices/search")
async def search_prices(
    hospital_id: str | None = None,
    code_type: str | None = None,
    code: str | None = None,
    care_setting: str | None = None,
    charge_type: str | None = None,
    db=Depends(get_public_db),
):
    rows = await prices_repo.search_prices(
        db,
        hospital_id=hospital_id,
        code_type=code_type,
        code=code,
        care_setting=care_setting,
        charge_type=charge_type,
    )
    out = [price_reference(r).model_dump(mode="json") for r in rows]
    return ok(out)
