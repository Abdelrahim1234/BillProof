from fastapi import APIRouter, Depends

from billproof.api.dependencies import get_current_case, get_private_db
from billproof.errors import forbidden, not_found, ok
from billproof.models import Case
from billproof.repositories import case_records
from billproof.repositories.cases import get_bill_line, get_bill_lines
from billproof.schemas.analysis import LineComparison
from billproof.schemas.explain import AskRequest, ExplainRequest, ExplainResponse
from billproof.services import activity
from billproof.services.explain import ask_case_question, explain_line

router = APIRouter(prefix="/api/v1", tags=["explain"])


def _require_matching_case(case_id: str, current: Case) -> None:
    if case_id != current.id:
        raise forbidden("Token does not match this case")


async def _latest_comparisons(db, case_id: str) -> list[LineComparison]:
    analysis = await case_records.get_latest_analysis(db, case_id)
    if not analysis:
        return []
    return [LineComparison.model_validate(c) for c in analysis.result_json["line_comparisons"]]


@router.post("/cases/{case_id}/lines/{line_id}/explain")
async def explain_bill_line(
    case_id: str,
    line_id: str,
    payload: ExplainRequest,
    current: Case = Depends(get_current_case),
    db=Depends(get_private_db),
):
    _require_matching_case(case_id, current)
    line = await get_bill_line(db, line_id)
    if not line or line.case_id != case_id:
        raise not_found("Bill line")

    comparisons = await _latest_comparisons(db, case_id)
    comparison = next((c for c in comparisons if c.line_id == line_id), None)

    result = await explain_line(current, line, comparison, payload.question)

    await activity.record(
        db,
        case_id=case_id,
        transport="rest",
        tool_name="explain_line",
        display_name="Explanation generated",
        status="success",
        # Never the question or answer text itself -- see services/explain.py.
        summary=f"Generated an explanation for one line item using {result.model}.",
    )
    return ok(ExplainResponse(answer=result.answer, model=result.model).model_dump(mode="json"))


@router.post("/cases/{case_id}/ask")
async def ask_about_case(
    case_id: str,
    payload: AskRequest,
    current: Case = Depends(get_current_case),
    db=Depends(get_private_db),
):
    _require_matching_case(case_id, current)
    lines = await get_bill_lines(db, case_id)
    comparisons = await _latest_comparisons(db, case_id)

    result = await ask_case_question(current, lines, comparisons, payload.question)

    await activity.record(
        db,
        case_id=case_id,
        transport="rest",
        tool_name="ask_case_question",
        display_name="Question answered",
        status="success",
        summary=f"Answered a patient question about this case using {result.model}.",
    )
    return ok(ExplainResponse(answer=result.answer, model=result.model).model_dump(mode="json"))
