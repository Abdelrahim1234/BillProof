from datetime import UTC, datetime

from billproof.models import ActivityReceipt
from billproof.repositories import case_records


async def case_uses_synthetic_demo_bill(db, case_id: str) -> bool:
    """Return whether the case came from the explicitly synthetic demo fixture.

    The marker is the internal receipt written only by ``POST /demo/cases``.
    Ordinary manual or uploaded bills therefore never inherit the demo notice.
    """
    return await case_records.case_used_demo_marker(db, case_id)


async def record(
    db,
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
        completed_at=datetime.now(UTC),
    )
    return await case_records.record_activity(db, receipt)
