from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from billproof.db import get_db
from billproof.errors import not_found, ok
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo
from billproof.schemas.facilities import FacilityDetail, FacilityOut
from billproof.services.privacy import price_reference

router = APIRouter(prefix="/api/v1", tags=["hospitals"])


@router.get("/hospitals")
def list_hospitals(
    name: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip: str | None = None,
    db: Session = Depends(get_db),
):
    rows = hospitals_repo.search_facilities(db, name=name, city=city, state=state, zip_code=zip)
    return ok([FacilityOut.model_validate(r).model_dump(mode="json") for r in rows])


@router.get("/hospitals/{hospital_id}")
def get_hospital(hospital_id: str, db: Session = Depends(get_db)):
    facility = hospitals_repo.get_facility(db, hospital_id)
    if not facility:
        raise not_found("Hospital")
    return ok(FacilityDetail.model_validate(facility).model_dump(mode="json"))


@router.get("/prices/search")
def search_prices(
    hospital_id: str | None = None,
    code_type: str | None = None,
    code: str | None = None,
    care_setting: str | None = None,
    charge_type: str | None = None,
    db: Session = Depends(get_db),
):
    rows = prices_repo.search_prices(
        db,
        hospital_id=hospital_id,
        code_type=code_type,
        code=code,
        care_setting=care_setting,
        charge_type=charge_type,
    )
    out = [price_reference(r).model_dump(mode="json") for r in rows]
    return ok(out)
