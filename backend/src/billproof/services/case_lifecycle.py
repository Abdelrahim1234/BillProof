from billproof.models import Case
from billproof.services.case_purge import purge_case as _purge_case


async def purge_case(db, case: Case) -> None:
    """Deletes a case and everything scoped to it, verified complete.

    Superseded services/case_purge.py's registry-based purge_case
    (CLAUDE_FINAL_DEMO_HARDENING_PROMPT Section 6) for the ad-hoc version
    that used to live here: that version only ever deleted the case's
    children (bill lines, analyses, packets, ...) -- the case document
    itself survived every "Delete my case" call, contradicting both this
    function's own docstring and docs/06's "Clear it on 'Delete my case'"
    invariant. Found while building verify_demo.py's cleanup step, which
    depends on deletion actually being complete.
    """
    await _purge_case(db, case)
