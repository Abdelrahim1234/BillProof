from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.models import PriceRecord


def search_prices(
    db: Session,
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
    stmt = select(PriceRecord)
    if hospital_id:
        stmt = stmt.where(PriceRecord.hospital_id == hospital_id)
    if code_type:
        stmt = stmt.where(PriceRecord.code_type == code_type)
    if code:
        stmt = stmt.where(PriceRecord.code == code)
    if care_setting:
        stmt = stmt.where(PriceRecord.care_setting == care_setting)
    if charge_type:
        stmt = stmt.where(PriceRecord.charge_type == charge_type)
    if payer_normalized:
        stmt = stmt.where(PriceRecord.payer_normalized == payer_normalized)
    if plan_normalized:
        stmt = stmt.where(PriceRecord.plan_normalized == plan_normalized)
    stmt = stmt.limit(limit)
    return list(db.scalars(stmt))


def prices_for_hospital_code(db: Session, hospital_id: str, code_type: str, code: str) -> list[PriceRecord]:
    stmt = select(PriceRecord).where(
        PriceRecord.hospital_id == hospital_id,
        PriceRecord.code_type == code_type,
        PriceRecord.code == code,
        PriceRecord.amount.is_not(None),
    )
    return list(db.scalars(stmt))


def prices_for_code_any_hospital(db: Session, code_type: str, code: str, exclude_hospital_id: str | None = None):
    stmt = select(PriceRecord).where(
        PriceRecord.code_type == code_type,
        PriceRecord.code == code,
        PriceRecord.amount.is_not(None),
    )
    if exclude_hospital_id:
        stmt = stmt.where(PriceRecord.hospital_id != exclude_hospital_id)
    return list(db.scalars(stmt))
