from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.api.dependencies import get_current_case
from billproof.db import get_db
from billproof.errors import AppError, forbidden, ok
from billproof.models import Analysis, Case
from billproof.services import activity, screens

router = APIRouter(prefix="/api/v1", tags=["screens"])


class PublishRequest(BaseModel):
    model_config = {"extra": "forbid"}

    room_code: str = Field(min_length=3, max_length=32)


@router.post("/cases/{case_id}/publish")
def publish_to_screen(
    case_id: str,
    payload: PublishRequest,
    current: Case = Depends(get_current_case),
    db: Session = Depends(get_db),
):
    """Sends this case's latest analysis to a presentation screen."""
    if case_id != current.id:
        raise forbidden("Token does not match this case")

    analysis = db.scalar(
        select(Analysis).where(Analysis.case_id == case_id).order_by(Analysis.created_at.desc())
    )
    if not analysis:
        raise AppError(
            "ANALYSIS_REQUIRED",
            "Run analysis on this case before sending it to the screen.",
            status_code=400,
        )

    submission = screens.publish(db, current, analysis, payload.room_code)
    db.commit()
    db.refresh(submission)

    activity.record(
        db,
        case_id=case_id,
        transport="rest",
        tool_name="publish_to_screen",
        display_name="Sent to presentation screen",
        status="success",
        summary="Sent this bill's comparison to the presentation screen in the room.",
    )
    return ok({"submission_id": submission.id, "room_code": submission.room_code})


@router.get("/screens/{room_code}/latest")
def latest_for_screen(room_code: str, db: Session = Depends(get_db)):
    """Polled by the presentation screen. Public by design: the room code is on
    a projector, and the payload holds only what the analysis already returned."""
    submission = screens.latest(db, room_code)
    if submission is None:
        return ok(None)
    return ok(
        {
            "submission_id": submission.id,
            "source_label": submission.source_label,
            "created_at": submission.created_at.isoformat(),
            **submission.payload_json,
        }
    )


@router.delete("/screens/{room_code}", status_code=204)
def clear_screen(room_code: str, db: Session = Depends(get_db)):
    """Clears the wall, useful between demo runs."""
    screens.clear(db, room_code)
    db.commit()
