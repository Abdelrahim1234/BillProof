from sqlalchemy import func, select
from sqlalchemy.orm import Session

from billproof.models import Facility, FacilityAssistance


def count_hospitals(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Facility)) or 0


def all_facility_ids(db: Session) -> list[str]:
    return list(db.scalars(select(Facility.id)))


def get_facility(db: Session, facility_id: str) -> Facility | None:
    return db.get(Facility, facility_id)


def search_facilities(
    db: Session,
    *,
    name: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
    limit: int = 25,
) -> list[Facility]:
    stmt = select(Facility)
    if name:
        stmt = stmt.where(Facility.name.ilike(f"%{name}%"))
    if city:
        stmt = stmt.where(Facility.city.ilike(f"%{city}%"))
    if state:
        stmt = stmt.where(Facility.state == state.upper())
    if zip_code:
        stmt = stmt.where(Facility.zip_code == zip_code)
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


def get_assistance(db: Session, facility_id: str) -> list[FacilityAssistance]:
    return list(
        db.scalars(select(FacilityAssistance).where(FacilityAssistance.facility_id == facility_id))
    )


def find_by_name_query(db: Session, query: str, state: str | None, limit: int = 10) -> list[Facility]:
    stmt = select(Facility).where(Facility.name.ilike(f"%{query}%"))
    if state:
        stmt = stmt.where(Facility.state == state.upper())
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt))
