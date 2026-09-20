"""Presentation-screen rooms.

A phone runs the normal case flow, then *publishes* the finished analysis to a
room code. The screen polls that room and renders it. What crosses over is a
display copy of numbers the analysis already produced, never the case access
token, and never anything the analysis itself would not have returned.

Invariant 9 still applies here, and more sharply: this content goes on a wall in
a room full of people. Free-text descriptions are re-masked on the way in,
because a hand-typed line never passed through extraction's masking.
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.errors import AppError
from billproof.models import Analysis, BillLine, Case, Facility, ScreenSubmission
from billproof.services.activity import case_uses_synthetic_demo_bill
from billproof.services.privacy import mask_identity_fields

ROOM_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{2,31}$")
SUBMISSION_TTL_HOURS = 12


def normalize_room_code(room_code: str) -> str:
    code = (room_code or "").strip()
    if not ROOM_CODE_PATTERN.match(code):
        raise AppError(
            "INVALID_ROOM_CODE",
            "Room code must be 3-32 letters, digits, or hyphens.",
            status_code=422,
            field="room_code",
        )
    return code.lower()


def _line_label(line: BillLine, *, allow_description: bool) -> dict:
    """Only what the screen needs to title a line.

    Free text a person typed never reaches the wall. Masking catches emails,
    phone numbers, labeled IDs and addresses, but no regex reliably catches a
    name, and this content is projected in a room. So descriptions ride along
    only for the synthetic example bill, whose text ships with the repo. For a
    real bill the screen titles the line by its billing code instead, which is
    the part the comparison is actually about.
    """
    description = line.description if (allow_description and line.description) else None
    return {
        "id": line.id,
        "code": line.code,
        "description": mask_identity_fields(description) if description else None,
    }


def build_payload(db: Session, case: Case, analysis: Analysis) -> dict:
    facility = db.get(Facility, case.hospital_id) if case.hospital_id else None
    lines = list(db.scalars(select(BillLine).where(BillLine.case_id == case.id)))
    is_demo = case_uses_synthetic_demo_bill(db, case.id)
    return {
        "hospital_name": facility.name if facility else None,
        "coverage_type": case.coverage_type,
        "is_demo_bill": is_demo,
        "analysis": {
            "analysis_id": analysis.id,
            "case_id": analysis.case_id,
            "created_at": analysis.created_at.isoformat(),
            **analysis.result_json,
        },
        "lines": [_line_label(line, allow_description=is_demo) for line in lines],
    }


def publish(db: Session, case: Case, analysis: Analysis, room_code: str) -> ScreenSubmission:
    """Replaces the room's contents with this bill. Caller commits."""
    code = normalize_room_code(room_code)

    # The screen shows one bill at a time, so keep exactly one. Dropping the
    # previous submission also means a bill leaves the wall the moment the next
    # person sends theirs.
    for stale in db.scalars(select(ScreenSubmission).where(ScreenSubmission.room_code == code)):
        db.delete(stale)

    submission = ScreenSubmission(
        room_code=code,
        case_id=case.id,
        source_label="example_bill" if case_uses_synthetic_demo_bill(db, case.id) else "own_bill",
        payload_json=build_payload(db, case, analysis),
    )
    db.add(submission)
    return submission


def latest(db: Session, room_code: str) -> ScreenSubmission | None:
    code = normalize_room_code(room_code)
    cutoff = datetime.utcnow() - timedelta(hours=SUBMISSION_TTL_HOURS)
    return db.scalar(
        select(ScreenSubmission)
        .where(ScreenSubmission.room_code == code, ScreenSubmission.created_at >= cutoff)
        .order_by(ScreenSubmission.created_at.desc())
    )


def clear(db: Session, room_code: str) -> int:
    """Empties a room. Caller commits."""
    code = normalize_room_code(room_code)
    rows = list(db.scalars(select(ScreenSubmission).where(ScreenSubmission.room_code == code)))
    for row in rows:
        db.delete(row)
    return len(rows)
