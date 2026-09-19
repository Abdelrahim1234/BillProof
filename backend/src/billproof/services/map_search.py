from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from billproof.enums import EvidenceAvailability, ObservedOrPublished
from billproof.models import Facility, PriceRecord
from billproof.schemas.common import Money
from billproof.schemas.map import (
    FacilitySearchResult,
    OutOfPocketEstimateResponse,
    PriceEvidenceItem,
)
from billproof.services.geo import haversine_miles

_PUBLISHED_CHARGE_TYPES = {"gross", "discounted_cash", "payer_negotiated", "deidentified_min", "deidentified_max"}


def _observed_or_published(charge_type: str) -> str:
    return (
        ObservedOrPublished.PUBLISHED.value
        if charge_type in _PUBLISHED_CHARGE_TYPES
        else ObservedOrPublished.OBSERVED_AGGREGATE.value
    )


def _fully_specified_for_exact_evidence(record: PriceRecord) -> bool:
    """An exact code alone is not enough to promise like-for-like evidence."""
    return (
        record.care_setting != "unknown"
        and record.charge_scope != "unknown"
        and record.rate_unit is not None
    )


def _record_limitations(record: PriceRecord) -> list[str]:
    limitations: list[str] = []
    if record.charge_scope == "unknown":
        limitations.append(
            "The public source does not identify whether this is a facility or professional charge."
        )
    if record.rate_unit is None:
        limitations.append(
            "The public source does not state a service unit; do not multiply this amount by bill units."
        )
    if record.charge_type == "gross":
        limitations.append("Gross charge is sticker price context, not a benchmark.")
    return limitations


def search_facilities(
    db: Session,
    *,
    lat: float,
    lng: float,
    radius_miles: float,
    service_code: str | None = None,
    code_type: str | None = None,
    facility_types: list[str] | None = None,
) -> list[FacilitySearchResult]:
    stmt = select(Facility)
    if facility_types:
        stmt = stmt.where(Facility.facility_type.in_(facility_types))
    facilities = list(db.scalars(stmt))

    results = []
    for f in facilities:
        if f.latitude is None or f.longitude is None:
            continue
        distance = haversine_miles(lat, lng, float(f.latitude), float(f.longitude))
        if distance > radius_miles:
            continue
        availability = (
            evidence_availability(db, f.id, service_code, code_type)
            if service_code and code_type
            else EvidenceAvailability.UNAVAILABLE.value
        )
        results.append(
            FacilitySearchResult(
                id=f.id,
                name=f.name,
                facility_type=f.facility_type,
                address=f.address,
                city=f.city,
                state=f.state,
                zip_code=f.zip_code,
                latitude=float(f.latitude),
                longitude=float(f.longitude),
                distance_miles=round(distance, 2),
                evidence_availability=availability,
            )
        )
    results.sort(key=lambda r: r.distance_miles)
    return results


def evidence_availability(db: Session, facility_id: str, service_code: str, code_type: str) -> str:
    exact = db.scalar(
        select(PriceRecord).where(
            PriceRecord.hospital_id == facility_id,
            PriceRecord.code_type == code_type,
            PriceRecord.code == service_code,
            PriceRecord.care_setting != "unknown",
            PriceRecord.charge_scope != "unknown",
            PriceRecord.rate_unit.is_not(None),
        )
    )
    if exact:
        return EvidenceAvailability.EXACT.value
    partial = db.scalar(
        select(PriceRecord).where(
            PriceRecord.hospital_id == facility_id,
            PriceRecord.code_type == code_type,
            PriceRecord.code == service_code,
        )
    )
    if partial:
        return EvidenceAvailability.PARTIAL.value
    from billproof.models import RegionalBenchmark

    regional = db.scalar(
        select(RegionalBenchmark).where(
            RegionalBenchmark.code_type == code_type, RegionalBenchmark.service_code == service_code
        )
    )
    if regional:
        return EvidenceAvailability.REGIONAL_CONTEXT.value
    return EvidenceAvailability.UNAVAILABLE.value


def price_evidence_for_facility(
    db: Session,
    facility: Facility,
    *,
    service_code: str,
    code_type: str,
    payer_name: str | None = None,
    plan_name: str | None = None,
) -> list[PriceEvidenceItem]:
    from billproof.services.code_normalizer import normalize_payer
    from billproof.services.privacy import citation_for_price_record

    stmt = select(PriceRecord).where(
        PriceRecord.hospital_id == facility.id,
        PriceRecord.code_type == code_type,
        PriceRecord.code == service_code,
    )
    rows = list(db.scalars(stmt))
    if payer_name:
        norm = normalize_payer(payer_name)
        rows = [r for r in rows if r.payer_normalized in (None, norm)]
    if plan_name:
        norm = normalize_payer(plan_name)
        rows = [r for r in rows if r.plan_normalized in (None, norm)]

    items = []
    for r in rows:
        exact_match = r.payer_name is None or (payer_name and r.payer_normalized == normalize_payer(payer_name))
        fully_specified = _fully_specified_for_exact_evidence(r)
        items.append(
            PriceEvidenceItem(
                amount_type=r.charge_type,
                observed_or_published=_observed_or_published(r.charge_type),
                money=Money.from_decimal(r.amount),
                facility_id=facility.id,
                facility_name=facility.name,
                facility_type=facility.facility_type,
                code=r.code,
                code_type=r.code_type,
                care_setting=r.care_setting,
                charge_scope=r.charge_scope,
                payer_name=r.payer_name,
                plan_name=r.plan_name,
                sample_count=r.allowed_count,
                data_year=r.mrf_date.year if r.mrf_date else None,
                match_tier="same_facility_exact_code" if r.care_setting != "unknown" else "same_facility_code_only",
                confidence="high" if exact_match and fully_specified else "medium",
                limitations=_record_limitations(r),
                source=citation_for_price_record(r),
                is_synthetic=r.is_synthetic,
            )
        )
    return items


def out_of_pocket_estimate(
    *,
    allowed_amount: Decimal,
    network_status: str,
    deductible_applicability: bool,
    remaining_deductible: Decimal | None,
    copay: Decimal | None,
    coinsurance_rate: Decimal | None,
    copay_interaction: str,
    remaining_oop_max: Decimal | None,
) -> OutOfPocketEstimateResponse:
    """docs/05's exact formula. Never caps an out-of-network balance bill at
    the allowed amount -- that branch returns billed-amount-bounded warnings
    instead of a point estimate."""
    warnings: list[str] = []
    unknowns: list[str] = []

    if network_status == "out_of_network":
        warnings.append(
            "This is an out-of-network scenario. An out-of-network provider can bill the patient for "
            "the difference between the charge and the plan's allowed amount; this estimate does not "
            "cap that balance bill at the allowed amount."
        )

    deductible_applied = (
        min(allowed_amount, remaining_deductible)
        if deductible_applicability and remaining_deductible is not None
        else Decimal(0)
    )
    if deductible_applicability and remaining_deductible is None:
        unknowns.append("remaining_deductible")
    post_deductible = max(Decimal(0), allowed_amount - deductible_applied)
    coinsurance_amount = post_deductible * (coinsurance_rate or Decimal(0))
    if coinsurance_rate is None:
        unknowns.append("coinsurance_rate")

    applicable_copay = copay or Decimal(0)
    if copay is None:
        unknowns.append("copay")

    def candidate(cp_applies: bool) -> Decimal:
        cp = applicable_copay if cp_applies else Decimal(0)
        return deductible_applied + cp + coinsurance_amount

    if copay_interaction == "instead_of":
        low = high = candidate(True) if applicable_copay else candidate(False)
    elif copay_interaction == "in_addition":
        low = high = candidate(True)
    else:
        unknowns.append("copay_interaction")
        low = candidate(False)
        high = candidate(True)
        warnings.append("Copay interaction with coinsurance is unknown; showing a bounded range.")

    if remaining_oop_max is None:
        unknowns.append("remaining_oop_max")

    if network_status == "out_of_network":
        # docs/05: never cap a possible out-of-network balance bill at the
        # allowed amount. Only an explicit remaining OOP max may bound it.
        low_estimate = min(low, remaining_oop_max) if remaining_oop_max is not None else low
        high_estimate = min(high, remaining_oop_max) if remaining_oop_max is not None else high
    else:
        cap = remaining_oop_max if remaining_oop_max is not None else allowed_amount
        low_estimate = min(allowed_amount, low, cap)
        high_estimate = min(allowed_amount, high, cap)

    return OutOfPocketEstimateResponse(
        low=Money.from_decimal(min(low_estimate, high_estimate)),
        high=Money.from_decimal(max(low_estimate, high_estimate)),
        components={
            "deductible_applied": str(deductible_applied),
            "coinsurance_amount": str(coinsurance_amount),
            "applicable_copay": str(applicable_copay),
        },
        assumptions=["In-network, adjudicated claim unless stated otherwise.", "Covered service, no exclusions applied."],
        unknowns=unknowns,
        warnings=warnings,
    )
