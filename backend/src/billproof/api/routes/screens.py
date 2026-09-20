import re
from copy import deepcopy

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from billproof.api.dependencies import get_current_case, get_private_db, get_public_db
from billproof.errors import forbidden, not_found, ok
from billproof.models import Case, ScreenSubmission
from billproof.repositories import case_records
from billproof.repositories import cases as cases_repo
from billproof.repositories import hospitals as hospitals_repo
from billproof.services import activity

router = APIRouter(prefix="/api/v1", tags=["screens"])

_ROOM_RE = re.compile(r"^[a-z0-9-]{12,32}$")


class PublishRequest(BaseModel):
    room_code: str = Field(min_length=12, max_length=32, pattern=r"^[A-Za-z0-9-]+$")


def _room(value: str) -> str:
    room_code = value.lower()
    if not _ROOM_RE.fullmatch(room_code):
        raise not_found("Screen")
    return room_code


def _analysis_payload(record, display_line_ids: dict[str, str]) -> dict:
    """Build a wall-only copy with no private case/analysis/line identifiers."""
    result = deepcopy(record.result_json)
    for comparison in result.get("line_comparisons", []):
        comparison["line_id"] = display_line_ids.get(comparison.get("line_id"), "unknown-line")
        for reference in comparison.get("references", []):
            # The citation remains usable without disclosing its persistence key.
            reference["price_record_id"] = None
    for finding in result.get("non_price_findings", []):
        finding["line_ids"] = [
            display_line_ids[line_id]
            for line_id in finding.get("line_ids", [])
            if line_id in display_line_ids
        ]
    return {"created_at": record.created_at.isoformat(), **result}


def _submission_payload(submission: ScreenSubmission) -> dict:
    return {
        "submission_id": submission.id,
        "source_label": submission.source_label,
        "created_at": submission.created_at.isoformat(),
        "hospital_name": submission.hospital_name,
        "coverage_type": submission.coverage_type,
        "is_demo_bill": submission.is_demo_bill,
        "analysis": submission.analysis_json,
        "lines": submission.lines_json,
    }


@router.post("/cases/{case_id}/publish")
async def publish_case_to_screen(
    case_id: str,
    payload: PublishRequest,
    current: Case = Depends(get_current_case),
    private_db=Depends(get_private_db),
    public_db=Depends(get_public_db),
):
    if case_id != current.id:
        raise forbidden("Token does not match this case")

    analysis = await case_records.get_latest_analysis(private_db, case_id)
    if not analysis:
        raise not_found("Analysis")
    lines = await cases_repo.get_bill_lines(private_db, case_id)
    is_demo = await activity.case_uses_synthetic_demo_bill(private_db, case_id)
    facility = (
        await hospitals_repo.get_active_facility(public_db, current.hospital_id)
        if current.hospital_id
        else None
    )

    # A real user's free text never reaches a shared screen. Demo descriptions
    # are bundled synthetic copy and safe to retain for readability.
    display_line_ids = {line.id: f"display-line-{index}" for index, line in enumerate(lines, start=1)}
    display_lines = [
        {
            "id": display_line_ids[line.id],
            "code": line.code,
            "description": line.description if is_demo else None,
        }
        for line in lines
    ]
    room_code = _room(payload.room_code)
    submission = ScreenSubmission(
        case_id=case_id,
        room_code=room_code,
        source_label="example_bill" if is_demo else "own_bill",
        hospital_name=facility.name if facility else None,
        coverage_type=current.coverage_type,
        is_demo_bill=is_demo,
        analysis_json=_analysis_payload(analysis, display_line_ids),
        lines_json=display_lines,
        expires_at=current.expires_at,
    )
    await case_records.publish_screen_submission(private_db, submission)
    await activity.record(
        private_db,
        case_id=case_id,
        transport="rest",
        tool_name="publish_to_screen",
        display_name="Comparison sent to presentation screen",
        status="success",
        summary="Published a privacy-reduced display copy to the presentation screen.",
    )
    return ok({"submission_id": submission.id, "room_code": room_code})


@router.get("/screens/{room_code}/latest")
async def latest_screen(room_code: str, db=Depends(get_private_db)):
    submission = await case_records.latest_screen_submission(db, _room(room_code))
    return ok(_submission_payload(submission) if submission else None)


@router.delete("/screens/{room_code}", status_code=204)
async def clear_screen(room_code: str, db=Depends(get_private_db)):
    await case_records.clear_screen_submissions(db, _room(room_code))
