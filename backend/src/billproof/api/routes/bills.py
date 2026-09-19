from decimal import Decimal

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.api.dependencies import get_current_case
from billproof.config import get_settings
from billproof.db import get_db
from billproof.errors import AppError, forbidden, not_found, ok
from billproof.models import BillLine, Case
from billproof.schemas.bills import BillLineOut, BulkConfirmRequest
from billproof.services import activity
from billproof.services.extraction import extract_bill

router = APIRouter(prefix="/api/v1", tags=["bills"])


def _require_matching_case(case_id: str, current: Case) -> None:
    if case_id != current.id:
        raise forbidden("Token does not match this case")


@router.post("/cases/{case_id}/bill/extract")
async def extract(
    case_id: str,
    file: UploadFile,
    current: Case = Depends(get_current_case),
    db: Session = Depends(get_db),
):
    _require_matching_case(case_id, current)
    settings = get_settings()
    max_bytes = settings.max_upload_mb * 1024 * 1024

    data = b""
    try:
        while chunk := await file.read(1024 * 1024):
            data += chunk
            if len(data) > max_bytes:
                raise AppError(
                    "UPLOAD_TOO_LARGE",
                    f"File exceeds the {settings.max_upload_mb} MB limit.",
                    status_code=413,
                )
        document = extract_bill(data, max_pdf_pages=settings.max_pdf_pages)
    finally:
        data = b""  # never persisted; drop the reference before returning
        await file.close()

    activity.record(
        db,
        case_id=current.id,
        transport="rest",
        tool_name="extract_bill",
        display_name="Bill upload processed",
        status="needs_manual_entry" if document.needs_manual_entry else "success",
        summary=f"Extracted {len(document.lines)} candidate line item(s) from an uploaded document.",
    )
    return ok(document.model_dump(mode="json"))


@router.post("/cases/{case_id}/bill/manual")
def manual_bill(
    case_id: str,
    payload: BulkConfirmRequest,
    current: Case = Depends(get_current_case),
    db: Session = Depends(get_db),
):
    _require_matching_case(case_id, current)
    lines = _insert_lines(db, current.id, payload.lines, confirmed=True)
    activity.record(
        db,
        case_id=current.id,
        transport="rest",
        tool_name="manual_bill",
        display_name="Manual bill entered",
        status="success",
        summary=f"Recorded {len(lines)} manually entered line item(s).",
    )
    return ok([_line_out(l) for l in lines])


@router.get("/cases/{case_id}/bill")
def get_bill(case_id: str, current: Case = Depends(get_current_case), db: Session = Depends(get_db)):
    _require_matching_case(case_id, current)
    lines = list(db.scalars(select(BillLine).where(BillLine.case_id == case_id)))
    return ok([_line_out(l) for l in lines])


class BillLinePatch(BaseModel):
    line_id: str
    expected_version: int
    code: str | None = None
    code_type: str | None = None
    description: str | None = None
    units: Decimal | None = None
    billed_amount: Decimal | None = None
    allowed_amount: Decimal | None = None
    insurer_paid: Decimal | None = None
    patient_responsibility: Decimal | None = None
    care_setting: str | None = None
    charge_scope: str | None = None
    confirmed: bool | None = None


@router.patch("/cases/{case_id}/bill")
def patch_bill_line(
    case_id: str,
    payload: BillLinePatch,
    current: Case = Depends(get_current_case),
    db: Session = Depends(get_db),
):
    _require_matching_case(case_id, current)
    line = db.get(BillLine, payload.line_id)
    if not line or line.case_id != case_id:
        raise not_found("Bill line")
    if line.version != payload.expected_version:
        raise AppError(
            "VERSION_CONFLICT",
            "This line was changed since you last loaded it.",
            status_code=409,
            retryable=True,
        )
    updates = payload.model_dump(exclude={"line_id", "expected_version"}, exclude_unset=True)
    for key, value in updates.items():
        setattr(line, key, value)
    line.version += 1
    db.commit()
    db.refresh(line)
    return ok(_line_out(line))


@router.post("/cases/{case_id}/lines/bulk")
def bulk_confirm(
    case_id: str,
    payload: BulkConfirmRequest,
    current: Case = Depends(get_current_case),
    db: Session = Depends(get_db),
):
    _require_matching_case(case_id, current)
    lines = _insert_lines(db, current.id, payload.lines, confirmed=True)
    activity.record(
        db,
        case_id=current.id,
        transport="rest",
        tool_name="bulk_confirm_lines",
        display_name="Bill lines confirmed",
        status="success",
        summary=f"Confirmed {len(lines)} line item(s) from extracted candidates.",
    )
    return ok([_line_out(l) for l in lines])


def _insert_lines(db: Session, case_id: str, inputs, *, confirmed: bool) -> list[BillLine]:
    lines = []
    for item in inputs:
        line = BillLine(
            case_id=case_id,
            code_raw=item.code_raw,
            code=item.code,
            code_type=item.code_type.value,
            modifiers=item.modifiers,
            description=item.description,
            units=item.units,
            rate_unit=item.rate_unit,
            billed_amount=item.billed_amount,
            allowed_amount=item.allowed_amount,
            insurer_paid=item.insurer_paid,
            patient_responsibility=item.patient_responsibility,
            charge_scope=item.charge_scope.value,
            care_setting=item.care_setting.value,
            confirmed=confirmed,
        )
        db.add(line)
        lines.append(line)
    db.commit()
    for line in lines:
        db.refresh(line)
    return lines


def _line_out(line: BillLine) -> dict:
    return BillLineOut.model_validate(line, from_attributes=True).model_dump(mode="json")
