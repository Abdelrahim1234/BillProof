from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.models import (
    ActivityReceipt,
    Analysis,
    BillLine,
    Case,
    CaseEvidence,
    Packet,
    PlanBenefitProfile,
)


def purge_case(db: Session, case: Case) -> None:
    """Deletes a case and everything scoped to it. Caller commits."""
    for model in (ActivityReceipt, Analysis, Packet, PlanBenefitProfile, CaseEvidence):
        for row in db.scalars(select(model).where(model.case_id == case.id)):
            db.delete(row)
    for line in db.scalars(select(BillLine).where(BillLine.case_id == case.id)):
        db.delete(line)
    db.delete(case)
