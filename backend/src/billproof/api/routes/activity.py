from fastapi import APIRouter, Depends

from billproof.api.dependencies import get_current_case, get_private_db
from billproof.errors import forbidden, ok
from billproof.models import Case
from billproof.repositories.case_records import list_activity
from billproof.schemas.common import ActivityReceiptOut

router = APIRouter(prefix="/api/v1", tags=["activity"])


@router.get("/cases/{case_id}/activity")
async def list_activity_route(case_id: str, current: Case = Depends(get_current_case), db=Depends(get_private_db)):
    if case_id != current.id:
        raise forbidden("Token does not match this case")
    rows = await list_activity(db, case_id)
    return ok([ActivityReceiptOut.model_validate(r, from_attributes=True).model_dump(mode="json") for r in rows])
