from fastapi import APIRouter, Depends

from billproof.api.dependencies import get_current_case, get_private_db, get_public_db
from billproof.errors import AppError, forbidden, not_found, ok
from billproof.models import Analysis, Case
from billproof.repositories.case_records import get_latest_analysis
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
async def run_analysis(
    case_id: str,
    current: Case = Depends(get_current_case),
    db=Depends(get_private_db),
    public_db=Depends(get_public_db),
):
    _require_matching_case(case_id, current)
    lines = await get_bill_lines(db, case_id)
    if not lines:
        raise AppError("NO_BILL_LINES", "This case has no bill lines to analyze.", status_code=400)

    analysis, _comparisons = await run_and_persist_analysis(public_db, db, current, lines)

    summary = analysis.result_json["summary"]
    await activity.record(
        db,
        case_id=case_id,
        transport="rest",
        tool_name="analyze_case",
        display_name="Bill analysis run",
        status="success",
        summary=(
            f"Compared {summary['total']} line item(s): {summary['compared']} scored, "
            f"{summary['context_only']} context only, {summary['insufficient_data']} without a defensible match."
        ),
    )
    return ok(_to_response(analysis))


@router.get("/cases/{case_id}/analysis/latest")
async def get_latest_analysis_route(
    case_id: str, current: Case = Depends(get_current_case), db=Depends(get_private_db)
):
    _require_matching_case(case_id, current)
    analysis = await get_latest_analysis(db, case_id)
    if not analysis:
        raise not_found("Analysis")
    return ok(_to_response(analysis))
