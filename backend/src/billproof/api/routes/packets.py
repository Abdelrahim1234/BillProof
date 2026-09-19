from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.api.dependencies import get_current_case
from billproof.db import get_db
from billproof.errors import AppError, forbidden, not_found, ok
from billproof.models import Analysis, Case, Packet
from billproof.repositories.cases import get_bill_lines
from billproof.repositories.hospitals import get_facility
from billproof.schemas.analysis import LineComparison
from billproof.schemas.packets import PacketRequest
from billproof.services import activity
from billproof.services.packet_builder import build_packet

router = APIRouter(prefix="/api/v1", tags=["packets"])


def _require_matching_case(case_id: str, current: Case) -> None:
    if case_id != current.id:
        raise forbidden("Token does not match this case")


@router.post("/cases/{case_id}/packet")
def create_packet(
    case_id: str,
    payload: PacketRequest,
    current: Case = Depends(get_current_case),
    db: Session = Depends(get_db),
):
    _require_matching_case(case_id, current)
    analysis = db.scalar(
        select(Analysis).where(Analysis.case_id == case_id).order_by(Analysis.created_at.desc())
    )
    if not analysis:
        raise AppError(
            "ANALYSIS_REQUIRED", "Run analysis on this case before building a packet.", status_code=400
        )

    lines = get_bill_lines(db, case_id)
    comparisons = [LineComparison.model_validate(c) for c in analysis.result_json["line_comparisons"]]
    hospital = get_facility(db, current.hospital_id) if current.hospital_id else None
    hospital_name = hospital.name if hospital else "your hospital"

    packet_json, markdown = build_packet(
        case=current,
        lines=lines,
        comparisons=comparisons,
        goal=payload.goal.value,
        language=payload.language.value,
        hospital_name=hospital_name,
        additional_context=payload.additional_context,
        bill_is_synthetic=activity.case_uses_synthetic_demo_bill(db, case_id),
    )

    packet = Packet(
        case_id=case_id,
        goal=payload.goal.value,
        language=payload.language.value,
        packet_json=packet_json,
        markdown=markdown,
    )
    db.add(packet)
    db.commit()
    db.refresh(packet)

    activity.record(
        db,
        case_id=case_id,
        transport="rest",
        tool_name="build_negotiation_packet",
        display_name="Negotiation packet prepared",
        status="success",
        summary=f"Prepared a {payload.language.value} negotiation packet from {len(comparisons)} cited findings.",
    )
    return ok(_to_response(packet))


@router.get("/cases/{case_id}/packet/latest")
def get_latest_packet(case_id: str, current: Case = Depends(get_current_case), db: Session = Depends(get_db)):
    _require_matching_case(case_id, current)
    packet = db.scalar(select(Packet).where(Packet.case_id == case_id).order_by(Packet.created_at.desc()))
    if not packet:
        raise not_found("Packet")
    return ok(_to_response(packet))


@router.get("/cases/{case_id}/packet/latest.pdf")
def get_latest_packet_pdf(case_id: str, current: Case = Depends(get_current_case)):
    _require_matching_case(case_id, current)
    raise AppError("NOT_IMPLEMENTED", "PDF packet export is not implemented in P0.", status_code=501)


def _to_response(packet: Packet) -> dict:
    return {
        "packet_id": packet.id,
        "case_id": packet.case_id,
        "goal": packet.goal,
        "language": packet.language,
        "packet": packet.packet_json,
        "markdown": packet.markdown,
    }
