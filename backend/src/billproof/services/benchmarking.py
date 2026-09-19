import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal

from billproof.enums import Confidence
from billproof.models import PriceRecord
from billproof.schemas.common import Money
from billproof.schemas.prices import BenchmarkSummary

_UNIT_SCALABLE_RATE_UNITS = {"per_unit", "per_service_unit"}


def scaled_amount(record: PriceRecord, units: Decimal) -> Decimal:
    """docs/03: respect rate units -- multiply only when the source explicitly
    says the rate is per unit."""
    if record.rate_unit in _UNIT_SCALABLE_RATE_UNITS and units and units != 1:
        return record.amount * units
    return record.amount


def representative_per_hospital(
    records: list[PriceRecord], units: Decimal = Decimal(1)
) -> dict[str, Decimal]:
    """One value per hospital first, so a hospital with many payer/plan rows
    does not dominate the cross-hospital median (docs/03)."""
    by_hospital: dict[str, list[Decimal]] = defaultdict(list)
    for r in records:
        by_hospital[r.hospital_id].append(scaled_amount(r, units))
    return {h: Decimal(str(statistics.median(amts))) for h, amts in by_hospital.items()}


def summarize(
    records: list[PriceRecord],
    *,
    basis: str,
    tier_name: str,
    confidence: str,
    limitations: list[str] | None = None,
    units: Decimal = Decimal(1),
) -> BenchmarkSummary:
    reps = representative_per_hospital(records, units)
    values = sorted(reps.values())
    median = Decimal(str(statistics.median(values)))
    return BenchmarkSummary(
        basis=basis,
        low=Money.from_decimal(values[0]),
        median=Money.from_decimal(median),
        high=Money.from_decimal(values[-1]),
        sample_size=len(records),
        match_tier=tier_name,
        confidence=confidence,
        limitations=limitations or [],
    )


def freshness_multiplier(records: list[PriceRecord], as_of: date | None = None) -> Decimal:
    """docs/03 freshness table, applied against the oldest record used."""
    as_of = as_of or date.today()
    ages = [
        (as_of - r.mrf_date).days
        for r in records
        if r.mrf_date is not None
    ]
    if not ages:
        return Decimal("0.60")  # unknown date = treat as poorly aligned
    oldest = max(ages)
    if oldest <= 400:
        return Decimal("1.00")
    if oldest <= 730:
        return Decimal("0.80")
    return Decimal("0.60")


def confidence_label(match_confidence: Decimal, freshness: Decimal) -> str:
    combined = match_confidence * freshness
    if combined >= Decimal("0.90"):
        return Confidence.HIGH.value
    if combined >= Decimal("0.70"):
        return Confidence.MEDIUM.value
    if combined > Decimal(0):
        return Confidence.LOW.value
    return Confidence.INSUFFICIENT.value
