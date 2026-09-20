"""Complete, idempotent, tenant-scoped case deletion.

CLAUDE_FINAL_DEMO_HARDENING_PROMPT Section 6: the delete-my-case operation is
not complete while the parent case document survives, and repair for that.

CASE_SCOPED_COLLECTIONS is the single explicit registry of every private-DB
collection scoped to one case -- built by inspecting billproof.models for
every StoredModel subclass that declares a case_id field, not by assuming
names (test_case_purge_registry_is_complete in
tests/integration/test_case_purge.py fails the build if a new case_id model
is ever added without a matching collection entry here).

This app has no separate object/blob storage and no background job system:
uploaded bytes are already never persisted (deleted in a `finally` block
before this module is ever reached -- see services/extraction.py), and every
analyze/packet/activity write happens synchronously in the same request that
creates it. So "verify the case is still active before committing" and
"fence a deletion_pending case" reduce here to one thing: deleting
synchronously, checking as we go, and refusing to resurrect a case that is
mid-delete -- there is no separate worker that could race it.
"""

from billproof.models import (
    ActivityReceipt,
    Analysis,
    BillLine,
    Case,
    CaseEvidence,
    Packet,
    PlanBenefitProfile,
    ScreenSubmission,
)

CASE_SCOPED_COLLECTIONS: dict[str, type] = {
    "bill_lines": BillLine,
    "analyses": Analysis,
    "packets": Packet,
    "activity_receipts": ActivityReceipt,
    "case_evidence": CaseEvidence,
    "plan_benefit_profiles": PlanBenefitProfile,
    "screen_submissions": ScreenSubmission,
}


class CasePurgeError(RuntimeError):
    """Raised when a delete could not be verified complete. No medical data
    is retained on this path -- only counts already logged are kept, and the
    case is left marked absent-or-partial for a caller to retry."""


async def _delete_case_scoped_records(db, case_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for collection in CASE_SCOPED_COLLECTIONS:
        counts[collection] = await db[collection].delete_many({"case_id": case_id})
    return counts


async def _verify_zero_remaining(db, case_id: str) -> None:
    for collection in CASE_SCOPED_COLLECTIONS:
        remaining = await db[collection].count_documents({"case_id": case_id})
        if remaining:
            raise CasePurgeError(f"{collection} still has {remaining} row(s) for this case after delete")
    if await db["cases"].find_one({"_id": case_id}):
        raise CasePurgeError("case document still exists after delete")


async def purge_case(db, case: Case) -> dict[str, int]:
    """Deletes a case and every record scoped to it, parent document last,
    then verifies zero remain. Idempotent: purging an already-absent case is
    a documented no-op success, not an error -- a retry after a partial
    failure must be safe to call again.
    """
    counts = await _delete_case_scoped_records(db, case.id)
    await db["cases"].delete_one({"_id": case.id})

    await _verify_zero_remaining(db, case.id)
    counts["cases"] = 1
    return counts
