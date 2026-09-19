from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.models import ActivityReceipt


def case_uses_synthetic_demo_bill(db: Session, case_id: str) -> bool:
    """Return whether the case came from the explicitly synthetic demo fixture.

    The marker is the internal receipt written only by ``POST /demo/cases``.
    Ordinary manual or uploaded bills therefore never inherit the demo notice.
    """
    receipt_id = db.scalar(
        select(ActivityReceipt.id)
        .where(
            ActivityReceipt.case_id == case_id,
            ActivityReceipt.transport == "internal",
            ActivityReceipt.tool_name == "create_demo_case",
        )
        .limit(1)
    )
    return receipt_id is not None


def record(
    db: Session,
    *,
    case_id: str,
    transport: str,
    tool_name: str,
    display_name: str,
    status: str,
    summary: str,
    source_ids: list[str] | None = None,
) -> ActivityReceipt:
    """Stores a safe, user-visible summary only -- never chain-of-thought,
    prompts, raw args, tokens, DB paths, or logs (docs/02)."""
    receipt = ActivityReceipt(
        case_id=case_id,
        transport=transport,
        tool_name=tool_name,
        display_name=display_name,
        status=status,
        summary=summary,
        source_ids=source_ids or [],
        completed_at=datetime.utcnow(),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt
