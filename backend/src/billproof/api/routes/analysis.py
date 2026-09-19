
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.api.dependencies import get_current_case
from billproof.db import get_db
from billproof.errors import AppError, forbidden, not_found, ok
from billproof.models import Analysis, Case
from billproof.repositories.cases import get_bill_lines
from billproof.services import activity
from billproof.services.analysis import run_and_persist_analysis

router = APIRouter(prefix="/api/v1", tags=["analysis"])


def _require_matching_case(case_id: str, current: Case) -> None:
    if case_id != current.id:
        raise forbidden("Token does not match this case")


def _to_response(analysis: Analysis) -> dict:
    return {"analysis_id": analysis.id, "case_id": analysis.case_id, "created_at": analysis.created_at.isoformat(), **analysis.result_json}


@router.post("/cases/{case_id}/analysis")
def run_analysis(case_id: str, current: Case = Depends(get_current_case), db: Session = Depends(get_db)):
    _require_matching_case(case_id, current)
    lines = get_bill_lines(db, case_id)
    if not lines:
        raise AppError("NO_BILL_LINES", "This case has no bill lines to analyze.", status_code=400)

    analysis, comparisons = run_and_persist_analysis(db, current, lines)

    scored = sum(1 for c in comparisons if c.comparison_status == "compared" and c.review_score is not None)
    unmatched = sum(1 for c in comparisons if c.comparison_status == "insufficient_data")
    activity.record(
        db,
        case_id=case_id,
        transport="rest",
        tool_name="analyze_case",
        display_name="Bill analysis run",
        status="success",
        summary=(
            f"Compared {len(comparisons)} line item(s): {scored} scored, "
            f"{unmatched} without a defensible match."
        ),
    )
    return ok(_to_response(analysis))


@router.get("/cases/{case_id}/analysis/latest")
def get_latest_analysis(
    case_id: str, current: Case = Depends(get_current_case), db: Session = Depends(get_db)
):
    _require_matching_case(case_id, current)
    analysis = db.scalar(
        select(Analysis).where(Analysis.case_id == case_id).order_by(Analysis.created_at.desc())
    )
    if not analysis:
        raise not_found("Analysis")
    return ok(_to_response(analysis))
