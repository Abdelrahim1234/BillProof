from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from billproof.api.dependencies import get_current_case
from billproof.db import get_db
from billproof.errors import forbidden, not_found, ok
from billproof.models import Case
from billproof.repositories import cases as cases_repo
from billproof.repositories import hospitals as hospitals_repo
from billproof.schemas.cases import CaseCreate, CaseCreated, CaseOut
from billproof.services import activity, demo_samples
from billproof.services.case_lifecycle import purge_case

router = APIRouter(prefix="/api/v1", tags=["cases"])


def _require_matching_case(case_id: str, current: Case) -> None:
    if case_id != current.id:
        raise forbidden("Token does not match this case")


@router.post("/cases", status_code=201)
def create_case(payload: CaseCreate, db: Session = Depends(get_db)):
    if payload.hospital_id and not hospitals_repo.get_facility(db, payload.hospital_id):
        raise not_found("Hospital")
    case, token = cases_repo.create_case(db, payload)
    return ok(
        CaseCreated(case_id=case.id, access_token=token, expires_at=case.expires_at).model_dump(mode="json")
    )


class DemoCaseRequest(BaseModel):
    model_config = {"extra": "forbid"}

    sample: str = demo_samples.DEFAULT_SAMPLE_ID


@router.get("/demo/samples")
def list_demo_samples():
    """The sample bills the start screen offers. All synthetic, all offline."""
    return ok(demo_samples.catalogue())


@router.post("/demo/cases", status_code=201)
def create_demo_case(payload: DemoCaseRequest | None = None, db: Session = Depends(get_db)):
    """Clones a synthetic sample bill into a fresh case. Must work fully offline
    (docs/04) -- everything here reads local fixtures only."""
    sample_id = (payload or DemoCaseRequest()).sample
    case, token, body = demo_samples.create_case_from_sample(db, sample_id)

    activity.record(
        db,
        case_id=case.id,
        transport="internal",
        tool_name="create_demo_case",
        display_name="Demo case created",
        status="success",
        summary=f"Loaded {len(body['lines'])} synthetic demo bill line items.",
    )

    return ok(
        {
            "case_id": case.id,
            "access_token": token,
            "expires_at": case.expires_at.isoformat(),
            "is_demo": True,
            "sample": sample_id,
            "title": body.get("title", "Example bill"),
        }
    )


@router.get("/cases/{case_id}")
def get_case(case_id: str, current: Case = Depends(get_current_case)):
    _require_matching_case(case_id, current)
    return ok(CaseOut.model_validate(current, from_attributes=True).model_dump(mode="json"))


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(case_id: str, current: Case = Depends(get_current_case), db: Session = Depends(get_db)):
    _require_matching_case(case_id, current)
    purge_case(db, current)
    db.commit()

