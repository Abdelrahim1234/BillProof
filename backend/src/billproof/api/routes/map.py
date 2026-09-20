from fastapi import APIRouter, Depends

from billproof.api.dependencies import get_current_case, get_private_db, get_public_db
from billproof.errors import forbidden, not_found, ok
from billproof.models import Case, CaseEvidence
from billproof.repositories import benchmarks as benchmarks_repo
from billproof.repositories import case_records
from billproof.repositories.hospitals import get_active_facility
from billproof.schemas.common import Money
from billproof.schemas.map import (
    AreaBenchmarkOut,
    CaseEvidenceCreate,
    CaseEvidenceOut,
    OutOfPocketEstimateRequest,
)
from billproof.services import activity, map_search
from billproof.services.privacy import strip_query

router = APIRouter(prefix="/api/v1", tags=["map"])

EVIDENCE_LAYERS = [
    {"layer": "published_cash", "label": "Published price, not insured responsibility"},
    {"layer": "your_plan", "label": "Negotiated rate, not final copay"},
    {"layer": "observed_public_payments", "label": "Observed/aggregate population and year"},
    {"layer": "assistance", "label": "Eligibility must be confirmed by the facility"},
    {"layer": "data_gaps", "label": "No public price found"},
]


@router.get("/map/search")
async def map_search_route(
    lat: float,
    lng: float,
    radius_miles: float = 25,
    service_code: str | None = None,
    code_type: str | None = None,
    facility_types: str | None = None,
    payer_name: str | None = None,
    plan_name: str | None = None,
    layers: str | None = None,
    db=Depends(get_public_db),
):
    types = facility_types.split(",") if facility_types else None
    results = await map_search.search_facilities(
        db, lat=lat, lng=lng, radius_miles=radius_miles, service_code=service_code, code_type=code_type,
        facility_types=types,
    )
    return ok([r.model_dump(mode="json") for r in results])


@router.get("/map/legend")
async def map_legend():
    return ok(EVIDENCE_LAYERS)


@router.get("/facilities/{facility_id}/price-evidence")
async def facility_price_evidence(
    facility_id: str,
    service_code: str,
    code_type: str,
    payer_name: str | None = None,
    plan_name: str | None = None,
    db=Depends(get_public_db),
):
    facility = await get_active_facility(db, facility_id)
    if not facility:
        raise not_found("Facility")
    items = await map_search.price_evidence_for_facility(
        db, facility, service_code=service_code, code_type=code_type, payer_name=payer_name, plan_name=plan_name
    )
    # Facilities are returned even when evidence is unavailable (docs/05).
    return ok([i.model_dump(mode="json") for i in items])


@router.get("/areas/{geography_type}/{geography_code}/benchmarks")
async def area_benchmarks(
    geography_type: str, geography_code: str, service_code: str, code_type: str, db=Depends(get_public_db)
):
    rows = await benchmarks_repo.search_regional_benchmarks(
        db, geography_type=geography_type, geography_code=geography_code, service_code=service_code, code_type=code_type
    )
    out = [
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
    return ok([o.model_dump(mode="json") for o in out])


@router.post("/estimates/out-of-pocket")
async def out_of_pocket_estimate(payload: OutOfPocketEstimateRequest):
    result = map_search.out_of_pocket_estimate(
        allowed_amount=payload.allowed_amount,
        network_status=payload.network_status,
        deductible_applicability=payload.deductible_applicability,
        remaining_deductible=payload.remaining_deductible,
        copay=payload.copay,
        coinsurance_rate=payload.coinsurance_rate,
        copay_interaction=payload.copay_interaction,
        remaining_oop_max=payload.remaining_oop_max,
    )
    return ok(result.model_dump(mode="json"))


@router.post("/cases/{case_id}/evidence")
async def add_case_evidence(
    case_id: str,
    payload: CaseEvidenceCreate,
    current: Case = Depends(get_current_case),
    private_db=Depends(get_private_db),
    public_db=Depends(get_public_db),
):
    if case_id != current.id:
        raise forbidden("Token does not match this case")

    snapshot: dict = {}
    if payload.facility_id:
        facility = await get_active_facility(public_db, payload.facility_id)
        if not facility:
            raise not_found("Facility")
        snapshot["facility_name"] = facility.name
        snapshot["facility_type"] = facility.facility_type
    if payload.regional_benchmark_id:
        rb = await benchmarks_repo.get_regional_benchmark(public_db, payload.regional_benchmark_id)
        if not rb:
            raise not_found("Regional benchmark")
        snapshot["regional_benchmark"] = {
            "geography_type": rb.geography_type,
            "geography_code": rb.geography_code,
            "source_url": strip_query(rb.source_url),
            "limitations": rb.limitations,
        }

    evidence = CaseEvidence(
        case_id=case_id,
        bill_line_id=payload.bill_line_id,
        facility_id=payload.facility_id,
        regional_benchmark_id=payload.regional_benchmark_id,
        match_tier=None,
        confidence="medium",
        snapshot_json=snapshot,
    )
    await case_records.create_evidence(private_db, evidence)

    # Adding evidence invalidates any prior packet built without it.
    await case_records.delete_packets_for_case(private_db, case_id)

    await activity.record(
        private_db,
        case_id=case_id,
        transport="rest",
        tool_name="add_map_evidence_to_case",
        display_name="Map evidence added",
        status="success",
        summary="Added one piece of local price evidence to this case; any existing packet was invalidated.",
    )
    return ok(_evidence_out(evidence))


@router.delete("/cases/{case_id}/evidence/{evidence_id}", status_code=204)
async def remove_case_evidence(
    case_id: str, evidence_id: str, current: Case = Depends(get_current_case), db=Depends(get_private_db)
):
    if case_id != current.id:
        raise forbidden("Token does not match this case")
    evidence = await case_records.get_evidence(db, evidence_id)
    if not evidence or evidence.case_id != case_id:
        raise not_found("Case evidence")
    await case_records.delete_evidence(db, evidence_id)


def _evidence_out(evidence: CaseEvidence) -> dict:
    return CaseEvidenceOut(
        id=evidence.id,
        case_id=evidence.case_id,
        bill_line_id=evidence.bill_line_id,
        facility_id=evidence.facility_id,
        regional_benchmark_id=evidence.regional_benchmark_id,
        match_tier=evidence.match_tier,
        confidence=evidence.confidence,
        snapshot_json=evidence.snapshot_json,
        created_at=evidence.created_at.isoformat(),
    ).model_dump(mode="json")
