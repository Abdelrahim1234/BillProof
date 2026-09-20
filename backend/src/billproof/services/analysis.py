import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from billproof.enums import AnalysisStatus, CoverageType
from billproof.models import BillLine, Case, PriceRecord
from billproof.schemas.analysis import ComparisonSubject, LineComparison, NonPriceFinding
from billproof.schemas.common import Money
from billproof.services import benchmarking, price_matching
from billproof.services.code_normalizer import normalize_payer
from billproof.services.privacy import citation_for_price_record

# FIX_BACKEND.md Fix 1: which benchmark bases are a scoreable (defensible,
# difference-producing) pair for a given comparison subject, straight from
# docs/03's benchmark-order lists. A basis outside this set for its subject
# is shown as context only -- e.g. a hospital's cash price anchored against
# an insured line's allowed amount (docs/03: "cash price as an alternative
# negotiation anchor only").
_SCOREABLE_BASIS_BY_SUBJECT: dict[str, frozenset[str]] = {
    "billed_amount": frozenset({"hospital_discounted_cash", "peer_discounted_cash"}),
    "patient_responsibility": frozenset({"hospital_discounted_cash", "peer_discounted_cash"}),
    "allowed_amount": frozenset(
        {
            "payer_negotiated_rate",
            "hospital_allowed_median",
            "peer_payer_negotiated_rate",
            "medicare_ffs_hospital_aggregate",
        }
    ),
}


def finalize_comparison_status(comparison: LineComparison) -> LineComparison:
    """The one tested function every analyze_* path routes through
    (FIX_BACKEND.md Fix 1). comparison_status is derived here, never trusted
    from whichever branch built the LineComparison.

    compared        ALL of: subject present; benchmark present with a median;
                     basis is a scoreable pair for that subject type;
                     difference is not None; >=1 source citation.
    context_only     a subject or a benchmark exists, but not a scoreable pair
                     -- never carries a difference, percent, or score.
    insufficient_data  neither a subject nor a benchmark.
    """
    subject = comparison.comparison_subject
    benchmark = comparison.benchmark
    has_median = bool(benchmark and benchmark.median is not None)
    is_scoreable_pair = bool(
        subject and has_median and benchmark.basis in _SCOREABLE_BASIS_BY_SUBJECT.get(subject.type, frozenset())
    )
    has_citation = bool(comparison.references)

    if subject and is_scoreable_pair and comparison.difference is not None and has_citation:
        status = "compared"
    elif subject is not None or benchmark is not None:
        status = "context_only"
    else:
        status = "insufficient_data"

    updates: dict = {"comparison_status": status}
    if status != "compared":
        # Defensive: a context_only/insufficient_data line never carries a
        # score-shaped number, regardless of what the branch that built it set.
        updates.update(
            difference=None,
            percent_above_benchmark=None,
            direction=None,
            finding_type=None,
            review_score=None,
            review_label=None,
            score_components=None,
        )
    return comparison.model_copy(update=updates)


REVIEW_LABEL_BANDS = [
    (0, 24, "limited_discrepancy_signal"),
    (25, 49, "review_recommended"),
    (50, 74, "strong_review_opportunity"),
    (75, 100, "high_review_opportunity"),
]


def review_label(score: int) -> str:
    for lo, hi, label in REVIEW_LABEL_BANDS:
        if lo <= score <= hi:
            return label
    return "high_review_opportunity"


def _clamp(value: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    return max(lo, min(hi, value))


# docs/03 base weights (sum to 100 when every component is available).
_SCORE_WEIGHTS: dict[str, Decimal] = {"gap": Decimal(60), "peer": Decimal(25), "documentation": Decimal(15)}


def compute_review_score(
    subject: Decimal,
    benchmark_median: Decimal,
    match_confidence: Decimal,
    freshness_confidence: Decimal,
    *,
    peer_percentile: Decimal | None = None,
    documentation_signal_hit: bool = False,
) -> tuple[int, dict[str, list[str]]]:
    """FIX_BACKEND.md Fix 5: renormalize across whichever components are
    actually available, so omitting one doesn't silently cap the score below
    its own top label. With peer omitted (its only reachable state today --
    see the ponytail note below), gap+documentation's 60/15 weights scale up
    to 80/20 so a large-enough gap can still reach high_review_opportunity
    (75+), instead of capping at (60+15)*0.90 ~= 68 while that label stays
    advertised as reachable.

    Returns (score, {"available": [...], "omitted": [...]}) -- gap and
    documentation are always computable from the subject/benchmark alone;
    peer is the only component that can be genuinely unavailable.
    """
    # ponytail: peer_percentile has no robust source with a 2-hospital seed;
    # treated as unavailable until a larger peer set exists.
    peer_available = peer_percentile is not None
    on = {"gap": True, "documentation": True, "peer": peer_available}
    available = [name for name in _SCORE_WEIGHTS if on[name]]
    omitted = [name for name in _SCORE_WEIGHTS if not on[name]]
    components = {"available": available, "omitted": omitted}

    if benchmark_median <= 0:
        return 0, {"available": [], "omitted": list(_SCORE_WEIGHTS)}

    scale = Decimal(100) / sum(_SCORE_WEIGHTS[name] for name in available)
    gap_ratio = (subject / benchmark_median - 1) / Decimal("1.0")
    gap_component = _SCORE_WEIGHTS["gap"] * scale * _clamp(gap_ratio, Decimal(0), Decimal(1))
    if peer_available:
        peer_component = _SCORE_WEIGHTS["peer"] * scale * _clamp(
            (peer_percentile - Decimal("0.50")) / Decimal("0.50"), Decimal(0), Decimal(1)
        )
    else:
        peer_component = Decimal(0)
    documentation_component = _SCORE_WEIGHTS["documentation"] * scale if documentation_signal_hit else Decimal(0)

    raw = (gap_component + peer_component + documentation_component) * match_confidence * freshness_confidence
    score = int(raw.to_integral_value(rounding=ROUND_HALF_UP))
    return score, components


def percent_above(subject: Decimal, benchmark_median: Decimal) -> str | None:
    if benchmark_median <= 0:
        return None
    pct = (subject / benchmark_median - Decimal(1)) * Decimal(100)
    return str(pct.quantize(Decimal("0.01")))


@dataclass(frozen=True)
class DifferenceResult:
    money: Money  # signed: negative means subject is below the benchmark
    percent: str | None  # signed
    direction: str  # above | below | matches
    finding_type: str  # above_benchmark | below_benchmark | matches_benchmark


def compute_difference(subject: Decimal, benchmark_median: Decimal) -> DifferenceResult:
    """The one domain helper for difference semantics (CLAUDE_FINAL_DEMO_HARDENING
    Fix 1). difference_cents is always subject - benchmark, signed; direction
    and finding_type are derived from its sign, never inferred later from a
    preformatted string. A below-benchmark result is not a smaller
    above-benchmark one -- callers must use `direction`, not assume "above"."""
    money = Money.from_decimal(subject - benchmark_median)
    if money.amount_cents > 0:
        direction, finding_type = "above", "above_benchmark"
    elif money.amount_cents < 0:
        direction, finding_type = "below", "below_benchmark"
    else:
        direction, finding_type = "matches", "matches_benchmark"
    return DifferenceResult(
        money=money,
        percent=percent_above(subject, benchmark_median),
        direction=direction,
        finding_type=finding_type,
    )


def _references(records: list[PriceRecord]) -> list[dict]:
    seen: set[tuple[str, str | None]] = set()
    refs = []
    for r in records:
        key = (r.source_url, r.source_record_locator)
        if key in seen:
            continue
        seen.add(key)
        refs.append(citation_for_price_record(r).model_dump(mode="json"))
    return refs


# Bases where the benchmark is a hospital's self-pay cash price, not a
# negotiated/allowed amount -- a cash price is context for negotiation, never
# proof of what insurance will ultimately make the patient owe.
_CASH_PRICE_BASES = frozenset({"hospital_discounted_cash", "peer_discounted_cash"})


def _direction_notes(basis: str, direction: str) -> list[str]:
    notes = []
    if direction == "below":
        notes.append(
            "This line is below the hospital's published cash price and does not show a pricing "
            "discrepancy based on this benchmark."
        )
    if basis in _CASH_PRICE_BASES:
        notes.append("A public cash price is not proof of your final insurance responsibility.")
    return notes


def _scored_comparison(
    line: BillLine,
    subject_type: str,
    subject_amount: Decimal,
    outcome: price_matching.MatchOutcome,
    basis: str,
    as_of: date,
) -> LineComparison:
    freshness = benchmarking.freshness_multiplier(outcome.records, as_of)
    confidence = benchmarking.confidence_label(outcome.confidence_base, freshness)
    summary = benchmarking.summarize(
        outcome.records,
        basis=basis,
        tier_name=outcome.tier_name,
        confidence=confidence,
        units=line.units,
    )
    median = summary.median.to_decimal()
    doc_signal = subject_amount > median * Decimal("1.05")
    score, score_components = compute_review_score(
        subject_amount, median, outcome.confidence_base, freshness, documentation_signal_hit=doc_signal
    )
    diff = compute_difference(subject_amount, median)
    return LineComparison(
        line_id=line.id,
        comparison_status="compared",
        comparison_subject=ComparisonSubject(type=subject_type, money=Money.from_decimal(subject_amount)),
        benchmark=summary,
        difference=diff.money,
        percent_above_benchmark=diff.percent,
        direction=diff.direction,
        finding_type=diff.finding_type,
        review_score=score,
        review_label=review_label(score),
        score_components=score_components,
        match=outcome.match,
        warnings=outcome.warnings + _direction_notes(basis, diff.direction),
        references=_references(outcome.records),
    )


def _context_only_comparison(
    line: BillLine,
    subject_type: str | None,
    subject_amount: Decimal | None,
    outcome: price_matching.MatchOutcome | None,
    basis: str,
    warnings: list[str],
    suggested_questions: list[str],
    as_of: date,
) -> LineComparison:
    benchmark = None
    if outcome is not None:
        freshness = benchmarking.freshness_multiplier(outcome.records, as_of)
        confidence = benchmarking.confidence_label(outcome.confidence_base, freshness)
        benchmark = benchmarking.summarize(
            outcome.records,
            basis=basis,
            tier_name=outcome.tier_name,
            confidence=confidence,
            limitations=["Shown as regional/contextual reference, not a like-for-like comparison."],
            units=line.units,
        )
    subject = None
    if subject_type and subject_amount is not None:
        subject = ComparisonSubject(type=subject_type, money=Money.from_decimal(subject_amount))
    return LineComparison(
        line_id=line.id,
        comparison_status="context_only",  # finalize_comparison_status is the actual arbiter; this is just honest-by-default
        comparison_subject=subject,
        benchmark=benchmark,
        difference=None,
        percent_above_benchmark=None,
        review_score=None,
        review_label=None,
        match=outcome.match if outcome else None,
        warnings=warnings + (outcome.warnings if outcome else []),
        suggested_questions=suggested_questions,
        references=_references(outcome.records) if outcome else [],
    )


def _insufficient(line: BillLine, reason: str, *, reason_code: str | None = None) -> LineComparison:
    return LineComparison(
        line_id=line.id,
        comparison_status="insufficient_data",
        warnings=[reason],
        reason_code=reason_code,
        suggested_questions=[
            "Please provide an itemized explanation of this charge, including the billing code and rate applied."
        ],
    )


async def analyze_self_pay(db, line: BillLine, case: Case, peer_hospital_ids: list[str], as_of: date) -> LineComparison:
    if not line.code or not case.hospital_id:
        return _insufficient(line, "Missing code or facility; cannot compare.")

    full_self_pay_balance = line.patient_responsibility is not None and (
        line.insurer_paid is None or line.insurer_paid == 0
    )
    if full_self_pay_balance:
        subject_type, subject_amount = "patient_responsibility", line.patient_responsibility
    elif line.billed_amount is not None:
        subject_type, subject_amount = "billed_amount", line.billed_amount
    else:
        return _insufficient(line, "No billed amount or patient responsibility on this line.")

    outcome = await price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=case.hospital_id,
        code_type=line.code_type,
        code=line.code,
        charge_type="discounted_cash",
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
        modifier=line.modifiers[0] if line.modifiers else None,
    )
    if outcome:
        return _scored_comparison(line, subject_type, subject_amount, outcome, "hospital_discounted_cash", as_of)

    outcome = await price_matching.find_peer_charge_type(
        db,
        hospital_id=case.hospital_id,
        peer_hospital_ids=peer_hospital_ids,
        code_type=line.code_type,
        code=line.code,
        charge_type="discounted_cash",
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
    )
    if outcome:
        return _scored_comparison(line, subject_type, subject_amount, outcome, "peer_discounted_cash", as_of)

    # Context-only fallback: de-identified min/max, never a midpoint score.
    min_outcome = await price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=case.hospital_id,
        code_type=line.code_type,
        code=line.code,
        charge_type="deidentified_min",
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
        modifier=None,
    )
    max_outcome = await price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=case.hospital_id,
        code_type=line.code_type,
        code=line.code,
        charge_type="deidentified_max",
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
        modifier=None,
    )
    if min_outcome and max_outcome:
        combined = price_matching.MatchOutcome(
            min_outcome.tier,
            min_outcome.tier_name,
            min_outcome.confidence_base,
            min_outcome.match,
            min_outcome.records + max_outcome.records,
        )
        return _context_only_comparison(
            line,
            subject_type,
            subject_amount,
            combined,
            "hospital_deidentified_range_context",
            ["No cash price on file; showing the de-identified allowed range as context only."],
            ["Would you consider the hospital's cash price for this service?"],
            as_of,
        )

    return _insufficient(
        line,
        "No cash price, peer price, or contextual range found for this code at this hospital.",
        reason_code="exact_code_not_found",
    )


async def analyze_commercial(db, line: BillLine, case: Case, peer_hospital_ids: list[str], as_of: date) -> LineComparison:
    if not line.code or not case.hospital_id:
        return _insufficient(line, "Missing code or facility; cannot compare.")

    modifier = line.modifiers[0] if line.modifiers else None
    if line.allowed_amount is None:
        cash_outcome = await price_matching.find_same_hospital_charge_type(
            db,
            hospital_id=case.hospital_id,
            code_type=line.code_type,
            code=line.code,
            charge_type="discounted_cash",
            care_setting=line.care_setting,
            charge_scope=line.charge_scope,
            modifier=modifier,
        )
        # FIX_BACKEND.md Fix 2: name the amount type the line actually
        # carries. The old single message claimed every one of these lines
        # had a patient-responsibility figure; most only have a billed charge.
        if line.patient_responsibility is not None:
            no_allowed_amount_warning = (
                "No allowed amount on this line; a patient-responsibility figure cannot be compared "
                "to a total negotiated rate."
            )
        elif line.billed_amount is not None:
            no_allowed_amount_warning = (
                "This line shows a billed charge but no allowed amount. Without the allowed amount "
                "from an EOB, a like-for-like insured comparison is not possible."
            )
        else:
            no_allowed_amount_warning = "This line has no billed amount, patient responsibility, or allowed amount on file."
        return _context_only_comparison(
            line,
            None,
            None,
            cash_outcome,
            "hospital_discounted_cash_anchor" if cash_outcome else "",
            [no_allowed_amount_warning],
            [
                "Please share the plan's Explanation of Benefits (EOB) showing the allowed amount for this line.",
                "Is a self-pay discount available if paid before insurance processes this claim?",
            ],
            as_of,
        )

    subject_amount = line.allowed_amount
    payer_norm = normalize_payer(case.payer_name)
    plan_norm = normalize_payer(case.plan_name)

    outcome = await price_matching.find_same_hospital_negotiated(
        db,
        hospital_id=case.hospital_id,
        code_type=line.code_type,
        code=line.code,
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
        modifier=modifier,
        payer_normalized=payer_norm,
        plan_normalized=plan_norm,
    )
    if outcome:
        return _scored_comparison(line, "allowed_amount", subject_amount, outcome, "payer_negotiated_rate", as_of)

    outcome = await price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=case.hospital_id,
        code_type=line.code_type,
        code=line.code,
        charge_type="allowed_median",
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
        modifier=modifier,
    )
    if outcome:
        return _scored_comparison(line, "allowed_amount", subject_amount, outcome, "hospital_allowed_median", as_of)

    outcome = await price_matching.find_peer_charge_type(
        db,
        hospital_id=case.hospital_id,
        peer_hospital_ids=peer_hospital_ids,
        code_type=line.code_type,
        code=line.code,
        charge_type="payer_negotiated",
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
    )
    if outcome:
        return _scored_comparison(line, "allowed_amount", subject_amount, outcome, "peer_payer_negotiated_rate", as_of)

    cash_outcome = await price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=case.hospital_id,
        code_type=line.code_type,
        code=line.code,
        charge_type="discounted_cash",
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
        modifier=modifier,
    )
    if cash_outcome:
        return _context_only_comparison(
            line,
            "allowed_amount",
            subject_amount,
            cash_outcome,
            "hospital_discounted_cash_anchor",
            ["Showing the hospital's cash price as a negotiation anchor only; it is not a substitute for the plan's negotiated rate."],
            ["Is a cash-price match available even though I have insurance?"],
            as_of,
        )

    return _insufficient(
        line,
        "No negotiated rate, allowed-amount benchmark, or cash-price anchor found for this code.",
        reason_code="exact_code_not_found",
    )


async def analyze_medicare(db, line: BillLine, case: Case, as_of: date) -> LineComparison:
    from billproof.repositories.benchmarks import get_medicare_benchmark

    if line.allowed_amount is None or not line.code or not case.hospital_id:
        return _insufficient(line, "Missing allowed amount, code, or facility for a Medicare FFS comparison.")

    row = await get_medicare_benchmark(db, case.hospital_id, line.code_type, line.code)
    if row and row.average_medicare_payment:
        freshness = Decimal("1.00") if (as_of.year - row.data_year) * 365 <= 400 else Decimal("0.80")
        confidence = benchmarking.confidence_label(Decimal("1.00"), freshness)
        median = Money.from_decimal(row.average_medicare_payment)
        summary_low = summary_high = median
        from billproof.schemas.prices import BenchmarkSummary

        summary = BenchmarkSummary(
            basis="medicare_ffs_hospital_aggregate",
            low=summary_low,
            median=median,
            high=summary_high,
            sample_size=row.service_count or 1,
            match_tier="same_hospital_ms_drg_apc_aggregate",
            confidence=confidence,
        )
        med = median.to_decimal()
        score, score_components = compute_review_score(line.allowed_amount, med, Decimal("1.00"), freshness)
        diff = compute_difference(line.allowed_amount, med)
        return LineComparison(
            line_id=line.id,
            comparison_status="compared",
            comparison_subject=ComparisonSubject(type="allowed_amount", money=Money.from_decimal(line.allowed_amount)),
            benchmark=summary,
            difference=diff.money,
            percent_above_benchmark=diff.percent,
            direction=diff.direction,
            finding_type=diff.finding_type,
            review_score=score,
            score_components=score_components,
            review_label=review_label(score),
            warnings=_direction_notes("medicare_ffs_hospital_aggregate", diff.direction),
            match=None,
        )

    outcome = await price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=case.hospital_id,
        code_type=line.code_type,
        code=line.code,
        charge_type="allowed_median",
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
        modifier=None,
    )
    if outcome:
        return _scored_comparison(line, "allowed_amount", line.allowed_amount, outcome, "hospital_allowed_median", as_of)

    return _insufficient(line, "No Medicare FFS aggregate or compatible public price found for this code.")


async def analyze_line(db, line: BillLine, case: Case, peer_hospital_ids: list[str], as_of: date | None = None) -> LineComparison:
    as_of = as_of or date.today()
    coverage = case.coverage_type
    if coverage == CoverageType.UNINSURED.value:
        result = await analyze_self_pay(db, line, case, peer_hospital_ids, as_of)
    elif coverage == CoverageType.MEDICARE_FFS.value:
        result = await analyze_medicare(db, line, case, as_of)
    elif coverage in (
        CoverageType.COMMERCIAL.value,
        CoverageType.MEDICARE_ADVANTAGE.value,
        CoverageType.MEDICAID_MANAGED.value,
    ):
        result = await analyze_commercial(db, line, case, peer_hospital_ids, as_of)
    else:
        result = _insufficient(line, "Coverage type unknown; cannot select a compatible benchmark.")
    return finalize_comparison_status(result)


def _duplicate_findings(lines: list[BillLine]) -> list[NonPriceFinding]:
    """FIX_BACKEND.md Fix 4: only code+modifiers+units+amount+SERVICE DATE all
    matching is a proven duplicate. BillLine has no per-line service date
    today (cases only store service_month) -- so a match on the other four
    fields is always reported as a *possible* duplicate, never asserted as
    one. Three CBCs across a multi-day inpatient stay is clinically ordinary;
    calling that a proven duplicate is a false positive."""
    groups: dict[tuple, list[str]] = {}
    for ln in lines:
        if not ln.code:
            continue
        key = (ln.code, tuple(ln.modifiers or []), str(ln.units), str(ln.billed_amount))
        groups.setdefault(key, []).append(ln.id)

    findings = []
    for ids in groups.values():
        if len(ids) < 2:
            continue
        n = len(ids)
        findings.append(
            NonPriceFinding(
                finding_type="possible_duplicate",
                description=f"{n} lines share the same code, units, and amount.",
                basis="user_confirmed_arithmetic",
                line_ids=ids,
                count=n,
                action=(
                    f"{n} lines share the same code, units, and amount. This can be normal for repeat "
                    "labs during a stay. Ask for the service date and time on each to confirm."
                ),
            )
        )
    return findings


def find_non_price_findings(lines: list[BillLine]) -> list[NonPriceFinding]:
    """FIX_BACKEND.md Fix 3: one aggregated finding per type, not one entry
    per line -- 18 lines missing a code is one finding with count=18, not 18
    copies of the same sentence."""
    findings = _duplicate_findings(lines)

    missing_code_ids = [ln.id for ln in lines if not ln.code]
    if missing_code_ids:
        n = len(missing_code_ids)
        findings.append(
            NonPriceFinding(
                finding_type="missing_code",
                description=f"{n} line(s) have no billing code.",
                basis="user_confirmed_arithmetic",
                line_ids=missing_code_ids,
                count=n,
                action=(
                    f"{n} lines have no portable billing code. Ask the hospital for the local/CDM or "
                    "revenue code, the NDC for medications, and the units for each of these items."
                ),
            )
        )

    unknown_setting_ids = [ln.id for ln in lines if ln.care_setting == "unknown"]
    if unknown_setting_ids:
        n = len(unknown_setting_ids)
        findings.append(
            NonPriceFinding(
                finding_type="unknown_care_setting",
                description=f"Care setting (inpatient/outpatient/emergency) could not be determined for {n} line(s).",
                basis="user_confirmed_arithmetic",
                line_ids=unknown_setting_ids,
                count=n,
                action="Ask the hospital's billing office to confirm the care setting for these items.",
            )
        )

    ambiguous_scope_ids = [ln.id for ln in lines if ln.charge_scope == "unknown"]
    if ambiguous_scope_ids:
        n = len(ambiguous_scope_ids)
        findings.append(
            NonPriceFinding(
                finding_type="facility_professional_ambiguity",
                description=f"Could not determine whether {n} line(s) are a facility or professional charge.",
                basis="user_confirmed_arithmetic",
                line_ids=ambiguous_scope_ids,
                count=n,
                action="Ask whether each of these charges is a facility fee or a professional (physician) fee.",
            )
        )
    return findings


def input_hash(case: Case, lines: list[BillLine]) -> str:
    payload = {
        "coverage_type": case.coverage_type,
        "payer_name": case.payer_name,
        "plan_name": case.plan_name,
        "hospital_id": case.hospital_id,
        "lines": [
            {
                "code": ln.code,
                "code_type": ln.code_type,
                "modifiers": ln.modifiers,
                "units": str(ln.units),
                "billed_amount": str(ln.billed_amount),
                "allowed_amount": str(ln.allowed_amount),
                "patient_responsibility": str(ln.patient_responsibility),
                "care_setting": ln.care_setting,
            }
            for ln in lines
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def run_case_analysis(
    public_db, case: Case, lines: list[BillLine], as_of: date | None = None
) -> tuple[list[LineComparison], list[NonPriceFinding], str]:
    """Shared by the REST analysis route and the MCP analyze_case tool
    (invariant 6: REST and MCP call the same service classes). ``public_db``
    is the read-only price/benchmark database -- this never writes."""
    from billproof.repositories.hospitals import all_facility_ids

    peer_hospital_ids = await all_facility_ids(public_db)
    comparisons = [await analyze_line(public_db, line, case, peer_hospital_ids, as_of) for line in lines]
    findings = find_non_price_findings(lines)
    status = overall_status(comparisons)
    return comparisons, findings, status


async def run_and_persist_analysis(public_db, private_db, case: Case, lines: list[BillLine]):
    """Runs the analysis against public price data and stores the result in
    the private, case-scoped ``analyses`` collection. Shared by the REST
    route and the MCP analyze_case tool so both persist identically."""
    from billproof.models import Analysis
    from billproof.repositories.case_records import create_analysis

    comparisons, findings, status = await run_case_analysis(public_db, case, lines)
    result_json = {
        "status": status,
        "line_comparisons": [c.model_dump(mode="json") for c in comparisons],
        "non_price_findings": [f.model_dump(mode="json") for f in findings],
        "summary": status_summary(comparisons),
    }
    record = Analysis(
        case_id=case.id, input_hash=input_hash(case, lines), status=status, result_json=result_json
    )
    await create_analysis(private_db, record)
    return record, comparisons


def overall_status(comparisons: list[LineComparison]) -> str:
    statuses = {c.comparison_status for c in comparisons}
    if statuses == {"insufficient_data"}:
        return AnalysisStatus.INSUFFICIENT_DATA.value
    if statuses == {"compared"}:
        return AnalysisStatus.COMPLETED.value
    return AnalysisStatus.PARTIAL.value  # any mix, including all-context_only: not every line got a defensible number


def status_summary(comparisons: list[LineComparison]) -> dict:
    """FIX_BACKEND.md Fix 1: the frontend stops counting by hand. Every count
    here is derived from comparison_status, never from code-presence or
    price_rows_found > 0."""
    counts = {"compared": 0, "context_only": 0, "insufficient_data": 0}
    for c in comparisons:
        counts[c.comparison_status] = counts.get(c.comparison_status, 0) + 1
    counts["total"] = len(comparisons)
    return counts
