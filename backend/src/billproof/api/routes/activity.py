from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.api.dependencies import get_current_case
from billproof.db import get_db
from billproof.errors import forbidden, ok
from billproof.models import ActivityReceipt, Case
from billproof.schemas.common import ActivityReceiptOut

router = APIRouter(prefix="/api/v1", tags=["activity"])


@router.get("/cases/{case_id}/activity")
def list_activity(case_id: str, current: Case = Depends(get_current_case), db: Session = Depends(get_db)):
    if case_id != current.id:
        raise forbidden("Token does not match this case")
    rows = list(db.scalars(select(ActivityReceipt).where(ActivityReceipt.case_id == case_id)))
    return ok([ActivityReceiptOut.model_validate(r, from_attributes=True).model_dump(mode="json") for r in rows])
