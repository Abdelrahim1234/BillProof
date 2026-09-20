from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from billproof import store
from billproof.models import BillLine, Case, Facility, FacilitySource, PriceRecord
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo
from billproof.services import analysis, benchmarking, price_matching


@pytest.fixture
def db():
    return store.get_public_db()


async def _facility(db, name="Test Hospital A"):
    f = Facility(name=name, facility_type="hospital", address="1 Main St", city="Blacksburg", state="VA", zip_code="24060")
    await hospitals_repo.upsert_facility(db, f)
    return f


async def _price(db, hospital_id, **overrides):
    source_url = overrides.get("source_url", "https://example.invalid/mrf.json")
    source = await hospitals_repo.get_facility_source(db, hospital_id, source_url=source_url)
    if not source:
        await hospitals_repo.upsert_facility_source(
            db,
            FacilitySource(
                hospital_id=hospital_id,
                source_type="test_verified_extract",
                source_url=source_url,
                sha256="a" * 64,
                active=True,
            ),
        )
    defaults = {
        "hospital_id": hospital_id,
        "code_type": "CPT",
        "code": "71046",
        "care_setting": "outpatient",
        "charge_type": "discounted_cash",
        "amount": Decimal("120.00"),
        "source_url": source_url,
        "citation_url": "https://example.invalid/pricing",
        "source_record_locator": "/test/row",
        "source_type": "test_verified_extract",
        "is_synthetic": False,
        "mrf_date": date.today(),
    }
    defaults.update(overrides)
    record = PriceRecord(**defaults)
    await prices_repo.upsert(db, record)
    return record


def _bill_line(case_id, **overrides):
    defaults = {"case_id": case_id, "code": "71046", "code_type": "CPT", "care_setting": "outpatient", "units": Decimal(1)}
    defaults.update(overrides)
    return BillLine(**defaults)


def _case(hospital_id, **overrides):
    import uuid

    defaults = {
        "access_token_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "hospital_id": hospital_id,
        "coverage_type": "uninsured",
        "language": "en",
        "expires_at": datetime.now(UTC) + timedelta(days=1),
    }
    defaults.update(overrides)
    return Case(**defaults)


async def test_exact_matching_never_crosses_code_types(db):
    hosp = await _facility(db)
    await _price(db, hosp.id, code_type="HCPCS", code="71046")  # different code_type, same digits
    outcome = await price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=hosp.id,
        code_type="CPT",
        code="71046",
        charge_type="discounted_cash",
        care_setting="outpatient",
        modifier=None,
    )
    assert outcome is None


async def test_cash_price_selected_for_self_pay(db):
    hosp = await _facility(db)
    await _price(db, hosp.id, charge_type="discounted_cash", amount=Decimal("120.00"))
    case = _case(hosp.id, coverage_type="uninsured")
    line = _bill_line(case.id, billed_amount=Decimal("450.00"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"
    assert result.benchmark.basis == "hospital_discounted_cash"
    assert result.review_score is not None
    assert result.review_score > 0


async def test_gross_charge_never_selected_as_benchmark(db):
    hosp = await _facility(db)
    await _price(db, hosp.id, charge_type="gross", amount=Decimal("450.00"))
    case = _case(hosp.id, coverage_type="uninsured")
    line = _bill_line(case.id, billed_amount=Decimal("450.00"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "insufficient_data"


async def test_no_midpoint_invented_from_min_max(db):
    hosp = await _facility(db)
    await _price(db, hosp.id, charge_type="deidentified_min", amount=Decimal("95.00"))
    await _price(db, hosp.id, charge_type="deidentified_max", amount=Decimal("310.00"))
    case = _case(hosp.id, coverage_type="uninsured")
    line = _bill_line(case.id, billed_amount=Decimal("450.00"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "context_only"
    assert result.review_score is None
    assert result.difference is None


def test_score_reaches_high_review_opportunity_with_only_gap_and_documentation():
    """FIX_BACKEND.md Fix 5: with peer_percentile unavailable, gap and
    documentation renormalize to fill its weight, so a large enough gap can
    still reach the top label -- it must not be capped at
    (60+15)*confidence*freshness ~= 68 while high_review_opportunity (75+)
    stays advertised as reachable."""
    score, components = analysis.compute_review_score(
        Decimal("450.00"),
        Decimal("100.00"),  # gap_ratio clamps to 1 (well over 100% above benchmark)
        Decimal("0.90"),  # a real, non-perfect confidence -- not the tier-1 1.00 edge case
        Decimal("1.00"),
        peer_percentile=None,
        documentation_signal_hit=True,
    )
    assert components == {"available": ["gap", "documentation"], "omitted": ["peer"]}
    assert score == 90  # (80+20) * 0.90 * 1.00
    assert analysis.review_label(score) == "high_review_opportunity"


def test_score_without_documentation_signal_is_lower_but_still_renormalized():
    score, components = analysis.compute_review_score(
        Decimal("450.00"),
        Decimal("100.00"),
        Decimal("0.90"),
        Decimal("1.00"),
        peer_percentile=None,
        documentation_signal_hit=False,
    )
    assert components == {"available": ["gap", "documentation"], "omitted": ["peer"]}
    assert score == 72  # 80 * 0.90 * 1.00 (documentation component not earned)


def test_difference_direction_and_copy():
    """CLAUDE_FINAL_DEMO_HARDENING_PROMPT Fix 1: direction/finding_type are
    derived from the sign of difference_cents, never inferred from a
    preformatted "N%" string. Covers positive, negative, zero, one-cent, and
    rounding cases."""
    above = analysis.compute_difference(Decimal("1385.59"), Decimal("860.00"))
    assert above.money.amount_cents == 52559
    assert above.direction == "above"
    assert above.finding_type == "above_benchmark"

    below = analysis.compute_difference(Decimal("1100.00"), Decimal("1187.00"))
    assert below.money.amount_cents == -8700
    assert below.direction == "below"
    assert below.finding_type == "below_benchmark"
    assert below.percent == "-7.33"

    exact_match = analysis.compute_difference(Decimal("500.00"), Decimal("500.00"))
    assert exact_match.money.amount_cents == 0
    assert exact_match.direction == "matches"
    assert exact_match.finding_type == "matches_benchmark"

    one_cent_below = analysis.compute_difference(Decimal("99.99"), Decimal("100.00"))
    assert one_cent_below.money.amount_cents == -1
    assert one_cent_below.direction == "below"

    one_cent_above = analysis.compute_difference(Decimal("100.01"), Decimal("100.00"))
    assert one_cent_above.money.amount_cents == 1
    assert one_cent_above.direction == "above"

    # null/incompatible benchmark: percent is None, direction is still derivable from cents
    null_benchmark = analysis.compute_difference(Decimal("100.00"), Decimal(0))
    assert null_benchmark.percent is None
    assert null_benchmark.direction == "above"


async def test_71046_below_cash_price_card(db):
    """CLAUDE_FINAL_DEMO_HARDENING_PROMPT Fix 1 + Fix 5's stage-2 example:
    billed $1,100 vs. published cash $1,187 must score 0,
    limited_discrepancy_signal, direction=below -- never "-7.33% above"."""
    hosp = await _facility(db)
    await _price(db, hosp.id, code="71046", charge_type="discounted_cash", amount=Decimal("1187.00"))
    case = _case(hosp.id, coverage_type="uninsured")
    line = _bill_line(case.id, code="71046", billed_amount=Decimal("1100.00"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"
    assert result.difference.amount_cents == -8700
    assert result.direction == "below"
    assert result.finding_type == "below_benchmark"
    assert result.review_score == 0
    assert result.review_label == "limited_discrepancy_signal"
    assert any("does not show a pricing discrepancy" in w for w in result.warnings)
    assert any("not proof of your final insurance responsibility" in w for w in result.warnings)


def test_percent_above_reports_the_difference_not_the_ratio():
    assert analysis.percent_above(Decimal("450.00"), Decimal("206.54")) == "117.88"


async def test_exact_payer_plan_selected_for_insured_allowed_amount(db):
    hosp = await _facility(db)
    await _price(
        db,
        hosp.id,
        charge_type="payer_negotiated",
        amount=Decimal("155.00"),
        payer_name="Cigna",
        payer_normalized="cigna",
        plan_name="Cigna PPO",
        plan_normalized="cigna ppo",
    )
    case = _case(hosp.id, coverage_type="commercial", payer_name="Cigna", plan_name="Cigna PPO")
    line = _bill_line(case.id, billed_amount=Decimal("450.00"), allowed_amount=Decimal("310.00"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"
    assert result.match.payer_exact is True
    assert result.match.plan_exact is True
    assert result.review_score is not None


async def test_patient_responsibility_never_compared_with_negotiated_rate_when_allowed_missing(db):
    hosp = await _facility(db)
    await _price(
        db,
        hosp.id,
        charge_type="payer_negotiated",
        amount=Decimal("58.00"),
        payer_name="Cigna",
        payer_normalized="cigna",
        plan_name="Cigna PPO",
        plan_normalized="cigna ppo",
        code="80053",
    )
    case = _case(hosp.id, coverage_type="commercial", payer_name="Cigna", plan_name="Cigna PPO")
    line = _bill_line(
        case.id, code="80053", billed_amount=Decimal("210.00"), patient_responsibility=Decimal("150.00")
    )

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    # No allowed amount AND no cash price seeded either -- genuinely nothing
    # to show, not even a contextual anchor.
    assert result.comparison_status == "insufficient_data"
    assert result.review_score is None
    assert result.difference is None


async def test_cash_price_anchor_for_insured_line_is_context_only_not_compared(db):
    """FIX_BACKEND.md Fix 1: an insured line with no allowed amount but a
    hospital cash price on file gets the cash price as a negotiation anchor
    -- a real subject and a real benchmark, but never a scoreable pair
    (docs/03: cash price is context for an insured line, not a comparison)."""
    hosp = await _facility(db)
    await _price(db, hosp.id, charge_type="discounted_cash", amount=Decimal("86.00"), code="80053")
    case = _case(hosp.id, coverage_type="commercial", payer_name="Cigna", plan_name="Cigna PPO")
    line = _bill_line(
        case.id, code="80053", billed_amount=Decimal("210.00"), patient_responsibility=Decimal("150.00")
    )

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "context_only"
    assert result.benchmark is not None
    assert result.benchmark.basis == "hospital_discounted_cash_anchor"
    assert result.review_score is None
    assert result.difference is None
    assert result.percent_above_benchmark is None


async def test_no_allowed_amount_warning_names_the_real_subject(db):
    """FIX_BACKEND.md Fix 2: the "no allowed amount" limitation must name
    what the line actually carries, not claim every such line has a
    patient-responsibility figure when most only have a billed charge."""
    hosp = await _facility(db)
    case = _case(hosp.id, coverage_type="commercial", payer_name="Cigna", plan_name="Cigna PPO")

    billed_only = _bill_line(case.id, code="80053", billed_amount=Decimal("210.00"))
    result = await analysis.analyze_line(db, billed_only, case, [hosp.id])
    assert not any("patient-responsibility" in w for w in result.warnings), (
        "a billed-amount-only line must not claim it has a patient-responsibility figure"
    )
    assert any("billed charge but no allowed amount" in w for w in result.warnings)

    with_patient_resp = _bill_line(
        case.id, code="80053", billed_amount=Decimal("210.00"), patient_responsibility=Decimal("150.00")
    )
    result2 = await analysis.analyze_line(db, with_patient_resp, case, [hosp.id])
    assert any("patient-responsibility" in w for w in result2.warnings)


def test_missing_code_findings_are_aggregated_not_repeated():
    """FIX_BACKEND.md Fix 3: one finding per type with a count, not one copy
    per line."""
    lines = [_bill_line("case-1", code=None, id=f"line-{i}") for i in range(18)]
    findings = analysis.find_non_price_findings(lines)

    missing_code = [f for f in findings if f.finding_type == "missing_code"]
    assert len(missing_code) == 1
    assert missing_code[0].count == 18
    assert len(missing_code[0].line_ids) == 18
    assert "18 lines have no portable billing code" in missing_code[0].action


def test_duplicate_lines_are_possible_not_proven():
    """FIX_BACKEND.md Fix 4: matching code/units/amount without a known
    service date is a *possible* duplicate, never asserted as proven -- three
    CBCs across a multi-day stay is clinically ordinary."""
    lines = [
        _bill_line("case-1", id="a", code="85027", units=Decimal(1), billed_amount=Decimal("304.53")),
        _bill_line("case-1", id="b", code="85027", units=Decimal(1), billed_amount=Decimal("304.53")),
        _bill_line("case-1", id="c", code="85027", units=Decimal(1), billed_amount=Decimal("304.53")),
    ]
    findings = analysis.find_non_price_findings(lines)

    assert not any(f.finding_type == "exact_duplicate_line" for f in findings)
    dup = next(f for f in findings if f.finding_type == "possible_duplicate")
    assert dup.count == 3
    assert set(dup.line_ids) == {"a", "b", "c"}
    assert "can be normal for repeat labs during a stay" in dup.action


async def test_facility_and_professional_never_mix(db):
    hosp = await _facility(db)
    await _price(db, hosp.id, charge_type="discounted_cash", amount=Decimal("999.00"), charge_scope="professional")
    outcome = await price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=hosp.id,
        code_type="CPT",
        code="71046",
        charge_type="discounted_cash",
        care_setting="outpatient",
        modifier=None,
        charge_scope="facility",
    )
    assert outcome is None


async def test_peer_median_uses_one_representative_value_per_hospital(db):
    hosp_a = await _facility(db, "Hospital A")
    await _price(db, hosp_a.id, charge_type="discounted_cash", amount=Decimal("100.00"))
    await _price(db, hosp_a.id, charge_type="discounted_cash", amount=Decimal("200.00"), payer_name="x", payer_normalized="x")
    await _price(db, hosp_a.id, charge_type="discounted_cash", amount=Decimal("300.00"), payer_name="y", payer_normalized="y")

    hosp_b = await _facility(db, "Hospital B")
    await _price(db, hosp_b.id, charge_type="discounted_cash", amount=Decimal("1000.00"))

    records = await prices_repo.query(
        db, [hosp_a.id, hosp_b.id], "CPT", "71046", charge_type="discounted_cash"
    )
    reps = benchmarking.representative_per_hospital(records)
    assert reps[hosp_a.id] == Decimal("200.00")  # median of 100/200/300, not swamped by 3 rows
    assert reps[hosp_b.id] == Decimal("1000.00")
    assert benchmarking.summarize(records, basis="x", tier_name="x", confidence="high").median.to_decimal() == Decimal(
        "600.00"
    )  # median of [200, 1000], not median of all 4 raw rows


def test_units_multiplied_only_when_rate_unit_explicit():
    hosp_id = "hosp-1"
    per_unit_record = PriceRecord(
        hospital_id=hosp_id,
        code_type="CPT",
        code="71046",
        care_setting="outpatient",
        charge_type="discounted_cash",
        amount=Decimal("10.00"),
        rate_unit="per_unit",
        source_url="https://example.invalid",
        is_synthetic=True,
    )
    plain_record = PriceRecord(
        hospital_id=hosp_id,
        code_type="CPT",
        code="80053",
        care_setting="outpatient",
        charge_type="discounted_cash",
        amount=Decimal("10.00"),
        source_url="https://example.invalid",
        is_synthetic=True,
    )
    assert benchmarking.scaled_amount(per_unit_record, Decimal(3)) == Decimal("30.00")
    assert benchmarking.scaled_amount(plain_record, Decimal(3)) == Decimal("10.00")


async def test_analysis_identical_when_only_locale_changes(db):
    hosp = await _facility(db)
    await _price(db, hosp.id, charge_type="discounted_cash", amount=Decimal("120.00"))
    case_en = _case(hosp.id, coverage_type="uninsured", language="en")
    case_es = _case(hosp.id, coverage_type="uninsured", language="es")
    line_en = _bill_line(case_en.id, billed_amount=Decimal("450.00"))
    line_es = _bill_line(case_es.id, billed_amount=Decimal("450.00"))

    result_en = await analysis.analyze_line(db, line_en, case_en, [hosp.id])
    result_es = await analysis.analyze_line(db, line_es, case_es, [hosp.id])

    assert result_en.review_score == result_es.review_score
    assert result_en.difference == result_es.difference


async def test_demo_gate_self_pay(db):
    """CLAUDE_FINAL_DEMO_HARDENING_PROMPT Fix 3 matrix row 1: self-pay with
    an exact same-facility benchmark must produce a real compared line."""
    hosp = await _facility(db)
    await _price(db, hosp.id, charge_type="discounted_cash", amount=Decimal("860.00"))
    case = _case(hosp.id, coverage_type="uninsured")
    line = _bill_line(case.id, billed_amount=Decimal("1385.59"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"
    assert result.difference is not None
    assert result.references


async def test_demo_gate_insured_without_eob(db):
    """Matrix row 2: an insured line with no allowed_amount, even with real
    priced evidence on file, must never fabricate a compared result -- zero
    compared lines is the correct, passing outcome."""
    hosp = await _facility(db)
    await _price(db, hosp.id, charge_type="discounted_cash", amount=Decimal("860.00"))
    case = _case(hosp.id, coverage_type="commercial", payer_name="Cigna", plan_name="NPR")
    line = _bill_line(case.id, billed_amount=Decimal("1385.59"))  # no allowed_amount: no EOB yet

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "context_only"
    assert result.review_score is None
    assert result.difference is None
    assert result.benchmark is not None  # real cited evidence is still shown, just not scored
    assert result.references


async def test_demo_gate_insured_with_compatible_eob(db):
    """Matrix row 4: an insured line with a final EOB (allowed_amount) and an
    exact payer/plan match must produce a real, scored comparison."""
    hosp = await _facility(db)
    await _price(
        db, hosp.id, charge_type="payer_negotiated", amount=Decimal("206.54"),
        payer_name="Cigna", payer_normalized="cigna", plan_name="NPR", plan_normalized="npr",
    )
    case = _case(hosp.id, coverage_type="commercial", payer_name="Cigna", plan_name="NPR")
    line = _bill_line(case.id, billed_amount=Decimal("450.00"), allowed_amount=Decimal("450.00"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"
    assert result.match.payer_exact is True
    assert result.match.plan_exact is True
    assert result.review_score is not None


async def test_85025_never_matches_85027(db):
    """CLAUDE_FINAL_DEMO_HARDENING_PROMPT Fix 4: 85025 (CBC w/ differential)
    and 85027 (CBC automated) are different services. A bill line coded
    85027 must never match a benchmark stored only under 85025."""
    hosp = await _facility(db)
    await _price(db, hosp.id, code="85025", charge_type="discounted_cash", amount=Decimal("120.00"))
    case = _case(hosp.id, coverage_type="uninsured")
    line = _bill_line(case.id, code="85027", billed_amount=Decimal("304.53"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "insufficient_data"
    assert result.reason_code == "exact_code_not_found"


async def test_exact_85027_match(db):
    """The other half of the pair: 85027 billed against 85027 benchmark data
    is a legitimate, eligible match."""
    hosp = await _facility(db)
    await _price(db, hosp.id, code="85027", charge_type="discounted_cash", amount=Decimal("120.00"))
    case = _case(hosp.id, coverage_type="uninsured")
    line = _bill_line(case.id, code="85027", billed_amount=Decimal("304.53"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"
    assert result.benchmark.median.amount_cents == 12000


async def test_85025_billed_against_85025_benchmark_matches(db):
    hosp = await _facility(db)
    await _price(db, hosp.id, code="85025", charge_type="discounted_cash", amount=Decimal("150.00"))
    case = _case(hosp.id, coverage_type="uninsured")
    line = _bill_line(case.id, code="85025", billed_amount=Decimal("304.53"))

    result = await analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"


def test_comparison_schema_rejects_protected_trait_fields():
    from pydantic import ValidationError

    from billproof.schemas.cases import CaseCreate

    with pytest.raises(ValidationError):
        CaseCreate(race="test")
