"""Repositories for every case-scoped side collection: analyses, packets,
activity receipts, and map evidence. Grouped together because
``purge_case_cascade`` (case deletion, invariant 9) must sweep all of them."""

from datetime import UTC, datetime

from billproof.models import (
    ActivityReceipt,
    Analysis,
    CaseEvidence,
    Packet,
    PlanBenefitProfile,
    ScreenSubmission,
)


async def create_analysis(db, analysis: Analysis) -> Analysis:
    await db["analyses"].insert_one(analysis.to_doc())
    return analysis


async def get_latest_analysis(db, case_id: str) -> Analysis | None:
    docs = await db["analyses"].find({"case_id": case_id}).sort("created_at", -1).limit(1).to_list()
    return Analysis.from_doc(docs[0]) if docs else None


async def create_packet(db, packet: Packet) -> Packet:
    await db["packets"].insert_one(packet.to_doc())
    return packet


async def get_latest_packet(db, case_id: str) -> Packet | None:
    docs = await db["packets"].find({"case_id": case_id}).sort("created_at", -1).limit(1).to_list()
    return Packet.from_doc(docs[0]) if docs else None


async def delete_packets_for_case(db, case_id: str) -> None:
    await db["packets"].delete_many({"case_id": case_id})


async def record_activity(db, receipt: ActivityReceipt) -> ActivityReceipt:
    await db["activity_receipts"].insert_one(receipt.to_doc())
    return receipt


async def list_activity(db, case_id: str) -> list[ActivityReceipt]:
    docs = await db["activity_receipts"].find({"case_id": case_id}).to_list()
    return [ActivityReceipt.from_doc(d) for d in docs]


async def case_used_demo_marker(db, case_id: str) -> bool:
    doc = await db["activity_receipts"].find_one(
        {"case_id": case_id, "transport": "internal", "tool_name": "create_demo_case"}
    )
    return doc is not None


async def create_evidence(db, evidence: CaseEvidence) -> CaseEvidence:
    await db["case_evidence"].insert_one(evidence.to_doc())
    return evidence


async def get_evidence(db, evidence_id: str) -> CaseEvidence | None:
    doc = await db["case_evidence"].find_one({"_id": evidence_id})
    return CaseEvidence.from_doc(doc) if doc else None


async def delete_evidence(db, evidence_id: str) -> None:
    await db["case_evidence"].delete_one({"_id": evidence_id})


async def publish_screen_submission(db, submission: ScreenSubmission) -> ScreenSubmission:
    # One privacy-reduced display copy per room; a new opt-in submission
    # atomically supersedes the prior screen state at this repository boundary.
    await db["screen_submissions"].delete_many({"room_code": submission.room_code})
    await db["screen_submissions"].insert_one(submission.to_doc())
    return submission


async def latest_screen_submission(db, room_code: str) -> ScreenSubmission | None:
    docs = (
        await db["screen_submissions"]
        # Mongo's TTL cleanup is asynchronous and the local file store does
        # not run TTL indexes. Enforce expiry on every public read so an old
        # presentation capability can never reveal a stale display copy.
        .find({"room_code": room_code, "expires_at": {"$gt": datetime.now(UTC)}})
        .sort("created_at", -1)
        .limit(1)
        .to_list()
    )
    return ScreenSubmission.from_doc(docs[0]) if docs else None


async def clear_screen_submissions(db, room_code: str) -> int:
    return await db["screen_submissions"].delete_many({"room_code": room_code})


async def purge_case_cascade(db, case_id: str) -> None:
    """Deletes a case and everything scoped to it (invariant 9 / delete-case
    endpoint). Idempotent: deleting an already-absent case is a no-op."""
    for collection in (
        "bill_lines",
        "analyses",
        "packets",
        "activity_receipts",
        "case_evidence",
        "plan_benefit_profiles",
        "screen_submissions",
    ):
        await db[collection].delete_many({"case_id": case_id})
    await db["cases"].delete_one({"_id": case_id})


__all__ = [
    "PlanBenefitProfile",
    "case_used_demo_marker",
    "clear_screen_submissions",
    "create_analysis",
    "create_evidence",
    "create_packet",
    "delete_evidence",
    "delete_packets_for_case",
    "get_evidence",
    "get_latest_analysis",
    "get_latest_packet",
    "latest_screen_submission",
    "list_activity",
    "publish_screen_submission",
    "purge_case_cascade",
    "record_activity",
]
