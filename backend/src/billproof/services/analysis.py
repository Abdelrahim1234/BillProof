import hashlib
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from billproof.enums import AnalysisStatus, CoverageType
from billproof.models import BillLine, Case, PriceRecord
from billproof.schemas.analysis import ComparisonSubject, LineComparison, NonPriceFinding
from billproof.schemas.common import Money
from billproof.services import benchmarking, price_matching
from billproof.services.code_normalizer import normalize_payer
from billproof.services.privacy import citation_for_price_record

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


def compute_review_score(
    subject: Decimal,
    benchmark_median: Decimal,
    match_confidence: Decimal,
    freshness_confidence: Decimal,
    *,
    peer_percentile: Decimal | None = None,
    documentation_signal_hit: bool = False,
) -> int:
    if benchmark_median <= 0:
        return 0
    gap_ratio = (subject / benchmark_median - 1) / Decimal("1.0")
    gap_component = Decimal(60) * _clamp(gap_ratio, Decimal(0), Decimal(1))
    # ponytail: peer_percentile has no robust source with a 2-hospital seed;
    # treated as unavailable (component=0) until a larger peer set exists.
    if peer_percentile is not None:
        peer_component = Decimal(25) * _clamp(
            (peer_percentile - Decimal("0.50")) / Decimal("0.50"), Decimal(0), Decimal(1)
        )
    else:
        peer_component = Decimal(0)
    documentation_signal = Decimal(15) if documentation_signal_hit else Decimal(0)
    raw = (gap_component + peer_component + documentation_signal) * match_confidence * freshness_confidence
    return int(raw.to_integral_value(rounding=ROUND_HALF_UP))


def percent_above(subject: Decimal, benchmark_median: Decimal) -> str | None:
    if benchmark_median <= 0:
        return None
    pct = (subject / benchmark_median - Decimal(1)) * Decimal(100)
    return str(pct.quantize(Decimal("0.01")))


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
    score = compute_review_score(subject_amount, median, outcome.confidence_base, freshness, documentation_signal_hit=doc_signal)
    difference = Money.from_decimal(subject_amount - median)
    return LineComparison(
        line_id=line.id,
        comparison_status="compared",
        comparison_subject=ComparisonSubject(type=subject_type, money=Money.from_decimal(subject_amount)),
        benchmark=summary,
        difference=difference,
        percent_above_benchmark=percent_above(subject_amount, median),
        review_score=score,
        review_label=review_label(score),
        match=outcome.match,
        warnings=outcome.warnings,
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
        comparison_status="compared",
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


def _insufficient(line: BillLine, reason: str) -> LineComparison:
    return LineComparison(
        line_id=line.id,
        comparison_status="insufficient_data",
        warnings=[reason],
        suggested_questions=[
            "Please provide an itemized explanation of this charge, including the billing code and rate applied."
        ],
    )


def analyze_self_pay(db: Session, line: BillLine, case: Case, peer_hospital_ids: list[str], as_of: date) -> LineComparison:
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

    outcome = price_matching.find_same_hospital_charge_type(
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

    outcome = price_matching.find_peer_charge_type(
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
    min_outcome = price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=case.hospital_id,
        code_type=line.code_type,
        code=line.code,
        charge_type="deidentified_min",
        care_setting=line.care_setting,
        charge_scope=line.charge_scope,
        modifier=None,
    )
    max_outcome = price_matching.find_same_hospital_charge_type(
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

    return _insufficient(line, "No cash price, peer price, or contextual range found for this code at this hospital.")


def analyze_commercial(db: Session, line: BillLine, case: Case, peer_hospital_ids: list[str], as_of: date) -> LineComparison:
    if not line.code or not case.hospital_id:
        return _insufficient(line, "Missing code or facility; cannot compare.")

    modifier = line.modifiers[0] if line.modifiers else None
    if line.allowed_amount is None:
        cash_outcome = price_matching.find_same_hospital_charge_type(
            db,
            hospital_id=case.hospital_id,
            code_type=line.code_type,
            code=line.code,
            charge_type="discounted_cash",
            care_setting=line.care_setting,
            charge_scope=line.charge_scope,
            modifier=modifier,
        )
        return _context_only_comparison(
            line,
            None,
            None,
            cash_outcome,
            "hospital_discounted_cash_anchor" if cash_outcome else "",
            ["No allowed amount on this line; a patient-responsibility figure cannot be compared to a total negotiated rate."],
            [
                "Please share the plan's Explanation of Benefits (EOB) showing the allowed amount for this line.",
                "Is a self-pay discount available if paid before insurance processes this claim?",
            ],
            as_of,
        )

    subject_amount = line.allowed_amount
    payer_norm = normalize_payer(case.payer_name)
    plan_norm = normalize_payer(case.plan_name)

    outcome = price_matching.find_same_hospital_negotiated(
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

    outcome = price_matching.find_same_hospital_charge_type(
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

    outcome = price_matching.find_peer_charge_type(
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

    cash_outcome = price_matching.find_same_hospital_charge_type(
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

    return _insufficient(line, "No negotiated rate, allowed-amount benchmark, or cash-price anchor found for this code.")


def analyze_medicare(db: Session, line: BillLine, case: Case, as_of: date) -> LineComparison:
    from sqlalchemy import select

    from billproof.models import MedicareBenchmark

    if line.allowed_amount is None or not line.code or not case.hospital_id:
        return _insufficient(line, "Missing allowed amount, code, or facility for a Medicare FFS comparison.")

    row = db.scalar(
        select(MedicareBenchmark).where(
            MedicareBenchmark.hospital_id == case.hospital_id,
            MedicareBenchmark.code_type == line.code_type,
            MedicareBenchmark.code == line.code,
            MedicareBenchmark.suppressed.is_(False),
        )
    )
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
        score = compute_review_score(line.allowed_amount, med, Decimal("1.00"), freshness)
        return LineComparison(
            line_id=line.id,
            comparison_status="compared",
            comparison_subject=ComparisonSubject(type="allowed_amount", money=Money.from_decimal(line.allowed_amount)),
            benchmark=summary,
            difference=Money.from_decimal(line.allowed_amount - med),
            percent_above_benchmark=percent_above(line.allowed_amount, med),
            review_score=score,
            review_label=review_label(score),
            match=None,
        )

    outcome = price_matching.find_same_hospital_charge_type(
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


def analyze_line(db: Session, line: BillLine, case: Case, peer_hospital_ids: list[str], as_of: date | None = None) -> LineComparison:
    as_of = as_of or date.today()
    coverage = case.coverage_type
    if coverage == CoverageType.UNINSURED.value:
        return analyze_self_pay(db, line, case, peer_hospital_ids, as_of)
    if coverage == CoverageType.MEDICARE_FFS.value:
        return analyze_medicare(db, line, case, as_of)
    if coverage in (
        CoverageType.COMMERCIAL.value,
        CoverageType.MEDICARE_ADVANTAGE.value,
        CoverageType.MEDICAID_MANAGED.value,
    ):
        return analyze_commercial(db, line, case, peer_hospital_ids, as_of)
    return _insufficient(line, "Coverage type unknown; cannot select a compatible benchmark.")


def find_non_price_findings(lines: list[BillLine]) -> list[NonPriceFinding]:
    findings: list[NonPriceFinding] = []

    seen: dict[tuple, list[str]] = {}
    for ln in lines:
        key = (ln.code, tuple(ln.modifiers or []), str(ln.units), str(ln.billed_amount))
        seen.setdefault(key, []).append(ln.id)
    for key, ids in seen.items():
        if len(ids) > 1 and key[0] is not None:
            findings.append(
                NonPriceFinding(
                    finding_type="exact_duplicate_line",
                    description=f"{len(ids)} lines share the same code, modifiers, units, and amount.",
                    basis="user_confirmed_arithmetic",
                    line_ids=ids,
                )
            )

    for ln in lines:
        if not ln.code:
            findings.append(
                NonPriceFinding(
                    finding_type="missing_code",
                    description="This line has no billing code.",
                    basis="user_confirmed_arithmetic",
                    line_ids=[ln.id],
                )
            )
        if ln.care_setting == "unknown":
            findings.append(
                NonPriceFinding(
                    finding_type="unknown_care_setting",
                    description="Care setting (inpatient/outpatient/emergency) could not be determined for this line.",
                    basis="user_confirmed_arithmetic",
                    line_ids=[ln.id],
                )
            )
        if ln.charge_scope == "unknown":
            findings.append(
                NonPriceFinding(
                    finding_type="facility_professional_ambiguity",
                    description="Could not determine whether this is a facility or professional charge.",
                    basis="user_confirmed_arithmetic",
                    line_ids=[ln.id],
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


def run_case_analysis(
    db: Session, case: Case, lines: list[BillLine], as_of: date | None = None
) -> tuple[list[LineComparison], list[NonPriceFinding], str]:
    """Shared by the REST analysis route and the MCP analyze_case tool
    (invariant 6: REST and MCP call the same service classes)."""
    from billproof.repositories.hospitals import all_facility_ids

    peer_hospital_ids = all_facility_ids(db)
    comparisons = [analyze_line(db, line, case, peer_hospital_ids, as_of) for line in lines]
    findings = find_non_price_findings(lines)
    status = overall_status(comparisons)
    return comparisons, findings, status


def run_and_persist_analysis(db: Session, case: Case, lines: list[BillLine]):
    """Runs the analysis and stores it as an Analysis row. Shared by the REST
    route and the MCP analyze_case tool so both persist identically."""
    from billproof.models import Analysis

    comparisons, findings, status = run_case_analysis(db, case, lines)
    result_json = {
        "status": status,
        "line_comparisons": [c.model_dump(mode="json") for c in comparisons],
        "non_price_findings": [f.model_dump(mode="json") for f in findings],
    }
    record = Analysis(
        case_id=case.id, input_hash=input_hash(case, lines), status=status, result_json=result_json
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, comparisons


def overall_status(comparisons: list[LineComparison]) -> str:
    statuses = {c.comparison_status for c in comparisons}
    if statuses == {"insufficient_data"}:
        return AnalysisStatus.INSUFFICIENT_DATA.value
    if "insufficient_data" in statuses or any(c.review_score is None for c in comparisons if c.comparison_status == "compared"):
        return AnalysisStatus.PARTIAL.value
    return AnalysisStatus.COMPLETED.value
