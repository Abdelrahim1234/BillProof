import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from billproof.db import SessionLocal
from billproof.models import BillLine, Case, Facility, PriceRecord
from billproof.services import analysis, benchmarking, price_matching


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.close()


def _facility(db, name="Test Hospital A"):
    f = Facility(name=name, facility_type="hospital", address="1 Main St", city="Blacksburg", state="VA", zip_code="24060")
    db.add(f)
    db.commit()
    return f


def _price(db, hospital_id, **overrides):
    defaults = {
        "hospital_id": hospital_id,
        "code_type": "CPT",
        "code": "71046",
        "care_setting": "outpatient",
        "charge_type": "discounted_cash",
        "amount": Decimal("120.00"),
        "source_url": "https://example.invalid",
        "is_synthetic": True,
        "mrf_date": date.today(),
    }
    defaults.update(overrides)
    record = PriceRecord(**defaults)
    db.add(record)
    db.commit()
    return record


def _bill_line(db, case_id, **overrides):
    defaults = {"case_id": case_id, "code": "71046", "code_type": "CPT", "care_setting": "outpatient", "units": Decimal(1)}
    defaults.update(overrides)
    line = BillLine(**defaults)
    db.add(line)
    db.commit()
    return line


def _case(db, hospital_id, **overrides):
    defaults = {
        "access_token_hash": uuid.uuid4().hex + uuid.uuid4().hex,
        "hospital_id": hospital_id,
        "coverage_type": "uninsured",
        "language": "en",
        "expires_at": date.today() + timedelta(days=1),
    }
    defaults.update(overrides)
    case = Case(**defaults)
    db.add(case)
    db.commit()
    return case


def test_exact_matching_never_crosses_code_types(db):
    hosp = _facility(db)
    _price(db, hosp.id, code_type="HCPCS", code="71046")  # different code_type, same digits
    outcome = price_matching.find_same_hospital_charge_type(
        db,
        hospital_id=hosp.id,
        code_type="CPT",
        code="71046",
        charge_type="discounted_cash",
        care_setting="outpatient",
        modifier=None,
    )
    assert outcome is None


def test_cash_price_selected_for_self_pay(db):
    hosp = _facility(db)
    _price(db, hosp.id, charge_type="discounted_cash", amount=Decimal("120.00"))
    case = _case(db, hosp.id, coverage_type="uninsured")
    line = _bill_line(db, case.id, billed_amount=Decimal("450.00"))

    result = analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"
    assert result.benchmark.basis == "hospital_discounted_cash"
    assert result.review_score is not None
    assert result.review_score > 0


def test_gross_charge_never_selected_as_benchmark(db):
    hosp = _facility(db)
    _price(db, hosp.id, charge_type="gross", amount=Decimal("450.00"))
    case = _case(db, hosp.id, coverage_type="uninsured")
    line = _bill_line(db, case.id, billed_amount=Decimal("450.00"))

    result = analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "insufficient_data"


def test_no_midpoint_invented_from_min_max(db):
    hosp = _facility(db)
    _price(db, hosp.id, charge_type="deidentified_min", amount=Decimal("95.00"))
    _price(db, hosp.id, charge_type="deidentified_max", amount=Decimal("310.00"))
    case = _case(db, hosp.id, coverage_type="uninsured")
    line = _bill_line(db, case.id, billed_amount=Decimal("450.00"))

    result = analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"
    assert result.review_score is None
    assert result.difference is None


def test_percent_above_reports_the_difference_not_the_ratio():
    assert analysis.percent_above(Decimal("450.00"), Decimal("206.54")) == "117.88"


def test_exact_payer_plan_selected_for_insured_allowed_amount(db):
    hosp = _facility(db)
    _price(
        db,
        hosp.id,
        charge_type="payer_negotiated",
        amount=Decimal("155.00"),
        payer_name="Cigna",
        payer_normalized="cigna",
        plan_name="Cigna PPO",
        plan_normalized="cigna ppo",
    )
    case = _case(db, hosp.id, coverage_type="commercial", payer_name="Cigna", plan_name="Cigna PPO")
    line = _bill_line(db, case.id, billed_amount=Decimal("450.00"), allowed_amount=Decimal("310.00"))

    result = analysis.analyze_line(db, line, case, [hosp.id])

    assert result.comparison_status == "compared"
    assert result.match.payer_exact is True
    assert result.match.plan_exact is True
    assert result.review_score is not None


def test_patient_responsibility_never_compared_with_negotiated_rate_when_allowed_missing(db):
    hosp = _facility(db)
    _price(
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
    case = _case(db, hosp.id, coverage_type="commercial", payer_name="Cigna", plan_name="Cigna PPO")
    line = _bill_line(
        db, case.id, code="80053", billed_amount=Decimal("210.00"), patient_responsibility=Decimal("150.00")
    )

    result = analysis.analyze_line(db, line, case, [hosp.id])

    assert result.review_score is None
    assert result.difference is None


def test_facility_and_professional_never_mix(db):
    hosp = _facility(db)
    _price(db, hosp.id, charge_type="discounted_cash", amount=Decimal("999.00"), charge_scope="professional")
    outcome = price_matching.find_same_hospital_charge_type(
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


def test_peer_median_uses_one_representative_value_per_hospital(db):
    hosp_a = _facility(db, "Hospital A")
    _price(db, hosp_a.id, charge_type="discounted_cash", amount=Decimal("100.00"))
    _price(db, hosp_a.id, charge_type="discounted_cash", amount=Decimal("200.00"), payer_name="x", payer_normalized="x")
    _price(db, hosp_a.id, charge_type="discounted_cash", amount=Decimal("300.00"), payer_name="y", payer_normalized="y")

    hosp_b = _facility(db, "Hospital B")
    _price(db, hosp_b.id, charge_type="discounted_cash", amount=Decimal("1000.00"))

    records = price_matching._query(
        db, [hosp_a.id, hosp_b.id], "CPT", "71046", charge_type="discounted_cash"
    )
    reps = benchmarking.representative_per_hospital(records)
    assert reps[hosp_a.id] == Decimal("200.00")  # median of 100/200/300, not swamped by 3 rows
    assert reps[hosp_b.id] == Decimal("1000.00")
    assert benchmarking.summarize(records, basis="x", tier_name="x", confidence="high").median.to_decimal() == Decimal(
        "600.00"
    )  # median of [200, 1000], not median of all 4 raw rows


def test_units_multiplied_only_when_rate_unit_explicit(db):
    hosp = _facility(db)
    per_unit_record = PriceRecord(
        hospital_id=hosp.id,
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
        hospital_id=hosp.id,
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


def test_analysis_identical_when_only_locale_changes(db):
    hosp = _facility(db)
    _price(db, hosp.id, charge_type="discounted_cash", amount=Decimal("120.00"))
    case_en = _case(db, hosp.id, coverage_type="uninsured", language="en")
    case_es = _case(db, hosp.id, coverage_type="uninsured", language="es")
    line_en = _bill_line(db, case_en.id, billed_amount=Decimal("450.00"))
    line_es = _bill_line(db, case_es.id, billed_amount=Decimal("450.00"))

    result_en = analysis.analyze_line(db, line_en, case_en, [hosp.id])
    result_es = analysis.analyze_line(db, line_es, case_es, [hosp.id])

    assert result_en.review_score == result_es.review_score
    assert result_en.difference == result_es.difference


def test_comparison_schema_rejects_protected_trait_fields():
    from pydantic import ValidationError

    from billproof.schemas.cases import CaseCreate

    with pytest.raises(ValidationError):
        CaseCreate(race="test")
