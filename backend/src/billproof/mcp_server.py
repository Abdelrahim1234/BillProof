"""BillBuster MCP server.

SDK note (see CLAUDE.md's caution about the brief's import line): the
installed package is `mcp==1.30.0`. `from mcp.server import MCPServer` does
not exist in this version. Verified at build time:

    >>> from mcp.server.fastmcp import FastMCP   # real high-level entry point

FastMCP gives typed Pydantic tool results, a resource decorator, and a
prompt decorator out of the box, which is what docs/04 asks for.

Every tool here calls the same repositories/services the REST routes call
(invariant 6) -- no tool ever makes a localhost HTTP request. Tools are async
and go through billproof.store the same way the REST app does; there is no
per-call session object to open/close the way SQLAlchemy needed.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from mcp.server.fastmcp import FastMCP

from billproof import store
from billproof.config import get_settings
from billproof.models import BillLine, Case
from billproof.repositories import benchmarks as benchmarks_repo
from billproof.repositories import case_records
from billproof.repositories import cases as cases_repo
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo
from billproof.schemas.analysis import LineComparison
from billproof.schemas.common import Money
from billproof.schemas.facilities import FacilityOut
from billproof.schemas.map import (
    AreaBenchmarkOut,
    FacilitySearchResult,
    OutOfPocketEstimateResponse,
    PriceEvidenceItem,
)
from billproof.schemas.mcp import ToolResult
from billproof.schemas.packets import PacketResponse
from billproof.schemas.prices import PriceReference
from billproof.services import activity, map_search
from billproof.services import explain as explain_service
from billproof.services.analysis import analyze_line, run_and_persist_analysis
from billproof.services.case_auth import tokens_match
from billproof.services.code_normalizer import normalize_payer
from billproof.services.packet_builder import build_packet
from billproof.services.privacy import (
    citation_for_price_record,
    price_reference,
    public_facility,
    strip_query,
)

_settings = get_settings()
mcp = FastMCP("billbuster", host=_settings.mcp_host, port=_settings.mcp_port)


class ToolError(ValueError):
    """Raised for a bad case_id/access_token or a missing prerequisite; the
    SDK surfaces this to the client as a tool error rather than a crash."""


async def _ensure_connected() -> None:
    """`mcp dev`/`mcp run` launch this module directly, bypassing the FastAPI
    lifespan that normally calls store.connect(); make every tool safe to
    call standalone."""
    await store.connect()


async def _require_case(db, case_id: str, access_token: str) -> Case:
    case = await cases_repo.get_case(db, case_id)
    if not case or not tokens_match(access_token, case.access_token_hash):
        raise ToolError("Invalid case_id or access_token.")
    if case.expires_at < datetime.now(UTC):
        raise ToolError("This case has expired.")
    if case.hospital_id and not await hospitals_repo.get_active_facility(
        store.get_public_db(), case.hospital_id
    ):
        raise ToolError("This case is outside the active market.")
    return case


@mcp.tool()
async def find_hospital(query: str, state: str | None = None, limit: int = 10) -> ToolResult[list[FacilityOut]]:
    """Find a seeded hospital/facility by name (optionally filtered by state)."""
    await _ensure_connected()
    rows = await hospitals_repo.find_by_name_query(store.get_public_db(), query, state, limit)
    data = [public_facility(r) for r in rows]
    return ToolResult(data=data, activity_summary=f"Searched hospitals matching '{query}'; found {len(data)}.")


@mcp.tool()
async def lookup_public_prices(
    hospital_id: str,
    code_type: str,
    code: str,
    modifier: str | None = None,
    care_setting: str | None = None,
    payer_name: str | None = None,
    plan_name: str | None = None,
) -> ToolResult[list[PriceReference]]:
    """Read-only lookup of cited public price records for one hospital and code.
    Never fetches anything live; only returns rows already ingested by the
    admin CLI."""
    await _ensure_connected()
    rows = await prices_repo.search_prices(
        store.get_public_db(), hospital_id=hospital_id, code_type=code_type, code=code, care_setting=care_setting
    )
    if payer_name:
        norm = normalize_payer(payer_name)
        rows = [r for r in rows if r.payer_normalized == norm]
    if plan_name:
        norm = normalize_payer(plan_name)
        rows = [r for r in rows if r.plan_normalized == norm]
    if modifier is not None:
        rows = [r for r in rows if r.modifier == modifier]
    data = [price_reference(r) for r in rows]
    return ToolResult(
        data=data, activity_summary=f"Looked up {code_type} {code} public prices; found {len(data)} record(s)."
    )


@mcp.tool()
async def compare_bill_line(
    hospital_id: str,
    code_type: str,
    code: str,
    comparison_amount: str,
    comparison_amount_type: Literal["billed_amount", "patient_responsibility", "allowed_amount"],
    units: str,
    coverage_type: str,
    modifier: str | None = None,
    care_setting: str | None = None,
    payer_name: str | None = None,
    plan_name: str | None = None,
    service_month: str | None = None,
) -> ToolResult[LineComparison]:
    """Compares one billed amount to a hospital's own disclosed prices.

    Runs through the exact same billproof.services.analysis.analyze_line used
    by the REST /cases/{id}/analysis path (invariant 6) -- for identical
    inputs the two return byte-identical comparison results. The transient
    line and case objects built here are never persisted."""
    try:
        amount = Decimal(comparison_amount)
        unit_qty = Decimal(units)
    except InvalidOperation as exc:
        raise ToolError("comparison_amount and units must be decimal strings.") from exc

    await _ensure_connected()
    if not await hospitals_repo.get_active_facility(store.get_public_db(), hospital_id):
        raise ToolError("Unknown hospital_id in the active market.")
    transient_case = Case(
        id="transient",
        access_token_hash="",
        hospital_id=hospital_id,
        coverage_type=coverage_type,
        payer_name=payer_name,
        plan_name=plan_name,
        service_month=service_month,
        expires_at=datetime.now(UTC),
    )
    transient_line = BillLine(
        id=str(uuid.uuid4()),
        case_id="transient",
        code_raw=code,
        code=code,
        code_type=code_type,
        modifiers=[modifier] if modifier else [],
        units=unit_qty,
        care_setting=care_setting or "unknown",
    )
    setattr(transient_line, comparison_amount_type, amount)

    peer_ids = await hospitals_repo.all_facility_ids(store.get_public_db())
    comparison = await analyze_line(store.get_public_db(), transient_line, transient_case, peer_ids)
    return ToolResult(
        data=comparison,
        activity_summary=f"Compared one {code_type} {code} line: {comparison.comparison_status}.",
    )


@mcp.tool()
async def analyze_case(case_id: str, access_token: str) -> ToolResult[dict]:
    """Runs the full deterministic analysis for a case's confirmed bill lines."""
    await _ensure_connected()
    private_db, public_db = store.get_private_db(), store.get_public_db()
    case = await _require_case(private_db, case_id, access_token)
    lines = await cases_repo.get_bill_lines(private_db, case_id)
    if not lines:
        raise ToolError("This case has no bill lines to analyze.")

    # Analysis reads public price/benchmark data; persistence is private-db.
    record, _comparisons = await run_and_persist_analysis(public_db, private_db, case, lines)
    counts = record.result_json["summary"]
    summary = (
        f"Compared {counts['total']} line item(s): {counts['compared']} scored, "
        f"{counts['context_only']} context only, {counts['insufficient_data']} without a defensible match."
    )

    await activity.record(
        private_db,
        case_id=case_id,
        transport="mcp",
        tool_name="analyze_case",
        display_name="Bill analysis run",
        status="success",
        summary=summary,
    )
    data = {"analysis_id": record.id, "case_id": case_id, **record.result_json}
    return ToolResult(data=data, activity_summary=summary)


@mcp.tool()
async def explain_bill_line(case_id: str, access_token: str, line_id: str, question: str | None = None) -> ToolResult[dict]:
    """Plain-language AI explanation of one bill line and its comparison
    result (Gemini). Code does the math; this only drafts prose -- it never
    invents a price, difference, or score (invariant 4). Requires the case's
    external_processing_consent to be true."""
    await _ensure_connected()
    private_db = store.get_private_db()
    case = await _require_case(private_db, case_id, access_token)
    line = await cases_repo.get_bill_line(private_db, line_id)
    if not line or line.case_id != case_id:
        raise ToolError("Bill line not found for this case.")

    analysis = await case_records.get_latest_analysis(private_db, case_id)
    comparison = None
    if analysis:
        comparisons = [LineComparison.model_validate(c) for c in analysis.result_json["line_comparisons"]]
        comparison = next((c for c in comparisons if c.line_id == line_id), None)

    result = await explain_service.explain_line(case, line, comparison, question)
    summary = f"Generated an AI explanation for one line item using {result.model}."
    await activity.record(
        private_db,
        case_id=case_id,
        transport="mcp",
        tool_name="explain_line",
        display_name="AI explanation generated",
        status="success",
        summary=summary,
    )
    return ToolResult(data={"answer": result.answer, "model": result.model}, activity_summary=summary)


@mcp.tool()
async def ask_about_case(case_id: str, access_token: str, question: str) -> ToolResult[dict]:
    """Plain-language AI answer to a free-text question about this case's
    bill and comparison results (Gemini). Same consent/invariant-4 rules as
    explain_bill_line."""
    await _ensure_connected()
    private_db = store.get_private_db()
    case = await _require_case(private_db, case_id, access_token)
    lines = await cases_repo.get_bill_lines(private_db, case_id)
    analysis = await case_records.get_latest_analysis(private_db, case_id)
    comparisons = (
        [LineComparison.model_validate(c) for c in analysis.result_json["line_comparisons"]] if analysis else []
    )

    result = await explain_service.ask_case_question(case, lines, comparisons, question)
    summary = f"Answered a patient question about this case using {result.model}."
    await activity.record(
        private_db,
        case_id=case_id,
        transport="mcp",
        tool_name="ask_case_question",
        display_name="AI question answered",
        status="success",
        summary=summary,
    )
    return ToolResult(data={"answer": result.answer, "model": result.model}, activity_summary=summary)


@mcp.tool()
async def find_assistance_options(hospital_id: str) -> ToolResult[dict]:
    """Returns financial-assistance URLs/contacts on file for a hospital.
    Eligibility must still be confirmed by the facility (docs/05)."""
    await _ensure_connected()
    db = store.get_public_db()
    facility = await hospitals_repo.get_active_facility(db, hospital_id)
    if not facility:
        raise ToolError("Unknown hospital_id.")
    rows = await hospitals_repo.get_assistance(db, hospital_id)
    if rows:
        options = [
            {
                "policy_url": strip_query(r.policy_url),
                "application_url": strip_query(r.application_url),
                "billing_phone": r.billing_phone,
                "languages": r.languages,
                "summary": r.summary,
                "source_url": strip_query(r.source_url),
                "last_verified_date": r.last_verified_date.isoformat() if r.last_verified_date else None,
            }
            for r in rows
        ]
    else:
        options = [
            {
                "policy_url": strip_query(facility.financial_assistance_url),
                "application_url": strip_query(facility.financial_assistance_url),
                "billing_phone": facility.phone,
                "languages": [],
                "summary": "Eligibility must be confirmed by the facility.",
                "source_url": strip_query(facility.financial_assistance_url),
                "last_verified_date": None,
            }
        ]
    return ToolResult(
        data={"hospital_id": hospital_id, "options": options},
        activity_summary=f"Looked up financial-assistance options for {facility.name}.",
    )


@mcp.tool()
async def build_negotiation_packet(
    case_id: str, access_token: str, goal: str, language: str
) -> ToolResult[PacketResponse]:
    """Builds a deterministic negotiation packet from the case's latest analysis."""
    from billproof.models import Packet

    await _ensure_connected()
    private_db, public_db = store.get_private_db(), store.get_public_db()
    case = await _require_case(private_db, case_id, access_token)
    analysis = await case_records.get_latest_analysis(private_db, case_id)
    if not analysis:
        raise ToolError("Run analyze_case on this case before building a packet.")

    lines = await cases_repo.get_bill_lines(private_db, case_id)
    comparisons = [LineComparison.model_validate(c) for c in analysis.result_json["line_comparisons"]]
    hospital = (
        await hospitals_repo.get_active_facility(public_db, case.hospital_id)
        if case.hospital_id
        else None
    )
    hospital_name = hospital.name if hospital else "your hospital"

    packet_json, markdown = build_packet(
        case=case,
        lines=lines,
        comparisons=comparisons,
        goal=goal,
        language=language,
        hospital_name=hospital_name,
        bill_is_synthetic=await activity.case_uses_synthetic_demo_bill(private_db, case_id),
    )
    packet = Packet(case_id=case_id, goal=goal, language=language, packet_json=packet_json, markdown=markdown)
    await case_records.create_packet(private_db, packet)

    summary = f"Prepared a {language} negotiation packet from {len(comparisons)} cited findings."
    await activity.record(
        private_db,
        case_id=case_id,
        transport="mcp",
        tool_name="build_negotiation_packet",
        display_name="Negotiation packet prepared",
        status="success",
        summary=summary,
    )
    response = PacketResponse(
        packet_id=packet.id, case_id=case_id, goal=goal, language=language, packet=packet_json, markdown=markdown
    )
    return ToolResult(data=response, activity_summary=summary)


@mcp.tool()
async def get_source_provenance(price_record_id: str) -> ToolResult[dict]:
    """Returns the source citation (URL, publisher, dates, synthetic flag) for
    one price record, so a client can show exactly where a number came from."""
    await _ensure_connected()
    db = store.get_public_db()
    record = await prices_repo.get_public_price(db, price_record_id)
    if not record:
        raise ToolError("Unknown price_record_id.")
    citation = citation_for_price_record(record)
    source = await hospitals_repo.get_facility_source(db, record.hospital_id, source_url=record.source_url)
    provenance = citation.model_dump(mode="json")
    provenance.update(
        {
            "price_record_id": record.id,
            "source_record_locator": record.source_record_locator,
            "schema_version": source.schema_version if source else None,
            "sha256": source.sha256 if source else None,
        }
    )
    return ToolResult(
        data=provenance,
        activity_summary=f"Looked up source provenance for one {record.code_type} {record.code} price record.",
    )


# --- ProofMap tools (docs/05-proofmap.md) ---

AMOUNT_TYPE_MEANING = {
    "gross": "Sticker price before discounts. Only compare against another gross charge for the same code/setting/units/date.",
    "discounted_cash": "Published self-pay price. Only compare against a self-pay balance, or as a cash-price request anchor.",
    "payer_negotiated": "Contracted provider-plan price. Only compare against an exact payer/plan match, or an allowed amount with caveats.",
    "deidentified_min": "Lower bound of a de-identified allowed-amount range. Context only -- never treat as a point estimate.",
    "deidentified_max": "Upper bound of a de-identified allowed-amount range. Context only -- never treat as a point estimate.",
    "allowed_p10": "10th percentile of de-identified allowed amounts for this hospital/code. Aggregate context, not a guarantee.",
    "allowed_median": "Median de-identified allowed amount. Compare against an exact payer/plan allowed amount, labeled as aggregate.",
    "allowed_p90": "90th percentile of de-identified allowed amounts. Aggregate context, not a guarantee.",
    "medicare_avg_payment": "CMS Medicare FFS average payment. A public benchmark for Medicare FFS coverage only.",
}


@mcp.tool()
async def find_nearby_facilities(
    lat: float,
    lng: float,
    radius_miles: float = 25,
    service_code: str | None = None,
    code_type: str | None = None,
    facility_types: list[str] | None = None,
) -> ToolResult[list[FacilitySearchResult]]:
    """Finds hospitals/urgent-care facilities within a radius. Facilities are
    returned even when price evidence is unavailable for the requested
    service (docs/05)."""
    await _ensure_connected()
    results = await map_search.search_facilities(
        store.get_public_db(),
        lat=lat,
        lng=lng,
        radius_miles=radius_miles,
        service_code=service_code,
        code_type=code_type,
        facility_types=facility_types,
    )
    return ToolResult(
        data=results, activity_summary=f"Found {len(results)} facility(ies) within {radius_miles} miles."
    )


@mcp.tool()
async def get_local_price_landscape(
    facility_id: str,
    service_code: str,
    code_type: str,
    payer_name: str | None = None,
    plan_name: str | None = None,
) -> ToolResult[list[PriceEvidenceItem]]:
    """Returns every cited public price-evidence item on file for one
    facility and code. An empty list is an honest 'no public price found',
    never a hospital price substituted in from elsewhere."""
    await _ensure_connected()
    db = store.get_public_db()
    facility = await hospitals_repo.get_active_facility(db, facility_id)
    if not facility:
        raise ToolError("Unknown facility_id.")
    items = await map_search.price_evidence_for_facility(
        db, facility, service_code=service_code, code_type=code_type, payer_name=payer_name, plan_name=plan_name
    )
    summary = (
        f"Found {len(items)} price-evidence item(s) for {facility.name}."
        if items
        else f"No public price found for this code at {facility.name}."
    )
    return ToolResult(data=items, activity_summary=summary)


@mcp.tool()
async def estimate_plan_cost_share(
    allowed_amount: str,
    network_status: str = "in_network",
    deductible_applicability: bool = True,
    remaining_deductible: str | None = None,
    copay: str | None = None,
    coinsurance_rate: str | None = None,
    copay_interaction: str = "unknown",
    remaining_oop_max: str | None = None,
) -> ToolResult[OutOfPocketEstimateResponse]:
    """Computes a bounded out-of-pocket estimate from plan terms. Never
    accepts or stores a member ID (docs/05)."""
    result = map_search.out_of_pocket_estimate(
        allowed_amount=Decimal(allowed_amount),
        network_status=network_status,
        deductible_applicability=deductible_applicability,
        remaining_deductible=Decimal(remaining_deductible) if remaining_deductible else None,
        copay=Decimal(copay) if copay else None,
        coinsurance_rate=Decimal(coinsurance_rate) if coinsurance_rate else None,
        copay_interaction=copay_interaction,
        remaining_oop_max=Decimal(remaining_oop_max) if remaining_oop_max else None,
    )
    return ToolResult(
        data=result,
        activity_summary=f"Estimated an out-of-pocket range of {result.low.amount_cents}-{result.high.amount_cents} cents.",
    )


@mcp.tool()
async def compare_area_prices(
    geography_type: str, geography_code: str, service_code: str, code_type: str
) -> ToolResult[list[AreaBenchmarkOut]]:
    """Returns regional/aggregate benchmarks for a service in an area. Never
    a substitute for an exact facility match -- regional context must not
    silently become an exact comparison (docs/05)."""
    await _ensure_connected()
    rows = await benchmarks_repo.search_regional_benchmarks(
        store.get_public_db(),
        geography_type=geography_type,
        geography_code=geography_code,
        service_code=service_code,
        code_type=code_type,
    )
    data = [
        AreaBenchmarkOut(
            geography_type=r.geography_type,
            geography_code=r.geography_code,
            service_code=r.service_code,
            code_type=r.code_type,
            amount_type=r.amount_type,
            observed_or_published=r.observed_or_published,
            payer_category=r.payer_category,
            plan_name=r.plan_name,
            p10=Money.from_decimal(r.p10),
            median=Money.from_decimal(r.median),
            p90=Money.from_decimal(r.p90),
            sample_count=r.sample_count,
            provider_count=r.provider_count,
            data_year=r.data_year,
            source_url=strip_query(r.source_url),
            suppressed=r.suppressed,
            limitations=r.limitations,
        )
        for r in rows
    ]
    return ToolResult(
        data=data, activity_summary=f"Found {len(data)} regional benchmark(s) for {geography_type} {geography_code}."
    )


@mcp.tool()
async def add_map_evidence_to_case(
    case_id: str,
    access_token: str,
    facility_id: str | None = None,
    bill_line_id: str | None = None,
    regional_benchmark_id: str | None = None,
) -> ToolResult[dict]:
    """Attaches a facility or regional benchmark as evidence on a case,
    snapshotting its provenance and invalidating any existing packet."""
    from billproof.models import CaseEvidence

    await _ensure_connected()
    private_db, public_db = store.get_private_db(), store.get_public_db()
    case = await _require_case(private_db, case_id, access_token)
    snapshot: dict = {}
    if facility_id:
        facility = await hospitals_repo.get_active_facility(public_db, facility_id)
        if not facility:
            raise ToolError("Unknown facility_id.")
        snapshot["facility_name"] = facility.name
        snapshot["facility_type"] = facility.facility_type
    if regional_benchmark_id:
        rb = await benchmarks_repo.get_regional_benchmark(public_db, regional_benchmark_id)
        if not rb:
            raise ToolError("Unknown regional_benchmark_id.")
        snapshot["regional_benchmark"] = {
            "geography_type": rb.geography_type,
            "source_url": strip_query(rb.source_url),
        }

    evidence = CaseEvidence(
        case_id=case.id,
        bill_line_id=bill_line_id,
        facility_id=facility_id,
        regional_benchmark_id=regional_benchmark_id,
        match_tier=None,
        confidence="medium",
        snapshot_json=snapshot,
    )
    await case_records.create_evidence(private_db, evidence)
    await case_records.delete_packets_for_case(private_db, case.id)

    summary = "Added one piece of local price evidence to this case; any existing packet was invalidated."
    await activity.record(
        private_db,
        case_id=case.id,
        transport="mcp",
        tool_name="add_map_evidence_to_case",
        display_name="Map evidence added",
        status="success",
        summary=summary,
    )
    return ToolResult(data={"evidence_id": evidence.id}, activity_summary=summary)


@mcp.tool()
async def explain_price_source(price_record_id: str) -> ToolResult[dict]:
    """Explains what one price record's amount type means and what it may
    and may not be compared against (docs/01)."""
    await _ensure_connected()
    db = store.get_public_db()
    record = await prices_repo.get_public_price(db, price_record_id)
    if not record:
        raise ToolError("Unknown price_record_id.")
    citation = citation_for_price_record(record)
    data = {
        "amount_type": record.charge_type,
        "meaning": AMOUNT_TYPE_MEANING.get(record.charge_type, "See methodology://pricing-comparison."),
        "source": citation.model_dump(mode="json"),
    }
    return ToolResult(
        data=data, activity_summary=f"Explained the {record.charge_type} amount type for one price record."
    )


@mcp.resource("methodology://pricing-comparison")
def methodology() -> str:
    """Explains charge types, amount compatibility, matching, scoring,
    privacy, and limitations (docs/01, docs/03)."""
    return """# BillBuster pricing-comparison methodology

## Amount types (never conflated)
Gross/billed charge, discounted cash price, payer-negotiated rate, total
allowed amount, insurer payment, patient responsibility, and de-identified
allowed percentiles are seven different values. Every comparison states
which type it used on both sides.

## Matching tiers (highest confidence first)
1. Same hospital, exact code/modifier/setting/payer/plan.
2. Same hospital, exact code/setting (cash price, or payer matched/plan unmatched).
3. Same hospital, exact code only (setting/modifier unknown).
4. Peer hospital, exact code/setting.
5. Description-only candidates are never scored automatically.

## Confidence and score
Confidence = match-tier base x freshness multiplier, mapped to
high/medium/low/insufficient. The review score blends how far the billed
amount exceeds the benchmark median, a peer-percentile signal (currently
disabled with a 2-hospital seed), and a documentation signal, then scales by
confidence and freshness. It is never a claim of fraud or illegality.

## Privacy
No patient name, DOB, street address, account number, MRN, member ID, email,
or phone is ever stored, compared on, or logged. Case tokens are stored only
as salted hashes.

## Limitations
This is a public-data comparison, not a legal or insurance determination,
and not a claim that a charge is illegal or that savings are guaranteed.
"""


@mcp.prompt()
def prepare_hospital_call(case_id: str, language: str, goal: str) -> str:
    """Instructs the host to analyze the case, cite the evidence it gets back,
    disclose limitations, and never state a number the tools did not return."""
    return (
        f"Call analyze_case for case_id={case_id!r} using the case credential only in the protected "
        "tool input, never in conversation or prompt text. Then call build_negotiation_packet for "
        f"the same case with goal={goal!r} and language={language!r}. Summarize the result for the "
        f"patient in {language}. Cite every number "
        "to the source_url and date the tools returned. State confidence and limitations for each line. "
        "Never state a price, difference, or score that did not come from a tool result. Never say a "
        "charge is illegal, fraudulent, or that savings are guaranteed -- use 'amount worth asking "
        "about' and 'potential review amount' instead."
    )


if __name__ == "__main__":
    mcp.run(transport=_settings.mcp_transport)
