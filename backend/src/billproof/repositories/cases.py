from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.config import get_settings
from billproof.models import BillLine, Case
from billproof.schemas.cases import CaseCreate
from billproof.services.case_auth import generate_token, hash_token


def create_case(db: Session, data: CaseCreate) -> tuple[Case, str]:
    token = generate_token()
    ttl = get_settings().case_ttl_hours
    case = Case(
        access_token_hash=hash_token(token),
        hospital_id=data.hospital_id,
        coverage_type=data.coverage_type.value,
        payer_name=data.payer_name,
        plan_name=data.plan_name,
        care_setting=data.care_setting.value,
        service_month=data.service_month,
        language=data.language.value,
        external_processing_consent=data.external_processing_consent,
        expires_at=datetime.utcnow() + timedelta(hours=ttl),
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case, token


def get_case(db: Session, case_id: str) -> Case | None:
    return db.get(Case, case_id)


def get_case_by_token(db: Session, token: str) -> Case | None:
    return db.scalar(select(Case).where(Case.access_token_hash == hash_token(token)))


def get_bill_lines(db: Session, case_id: str) -> list[BillLine]:
    return list(db.scalars(select(BillLine).where(BillLine.case_id == case_id)))
