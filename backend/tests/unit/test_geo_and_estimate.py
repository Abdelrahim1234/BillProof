from decimal import Decimal

from billproof.services.geo import haversine_miles
from billproof.services.map_search import out_of_pocket_estimate


def test_haversine_zero_distance():
    assert haversine_miles(37.2001, -80.4181, 37.2001, -80.4181) == 0


def test_haversine_known_distance_jfk_to_lax():
    distance = haversine_miles(40.6413, -73.7781, 33.9416, -118.4085)
    assert 2400 < distance < 2500


def test_out_of_pocket_deductible_not_met_caps_at_allowed():
    result = out_of_pocket_estimate(
        allowed_amount=Decimal("200.00"),
        network_status="in_network",
        deductible_applicability=True,
        remaining_deductible=Decimal("500.00"),
        copay=Decimal(0),
        coinsurance_rate=Decimal(0),
        copay_interaction="in_addition",
        remaining_oop_max=Decimal("1000.00"),
    )
    assert result.low.to_decimal() == Decimal("200.00")
    assert result.high.to_decimal() == Decimal("200.00")


def test_out_of_pocket_standard_scenario():
    result = out_of_pocket_estimate(
        allowed_amount=Decimal("200.00"),
        network_status="in_network",
        deductible_applicability=True,
        remaining_deductible=Decimal(0),
        copay=Decimal("30.00"),
        coinsurance_rate=Decimal("0.20"),
        copay_interaction="in_addition",
        remaining_oop_max=Decimal("1000.00"),
    )
    assert result.low.to_decimal() == Decimal("70.00")
    assert result.high.to_decimal() == Decimal("70.00")


def test_out_of_pocket_unknown_copay_interaction_is_bounded_range():
    result = out_of_pocket_estimate(
        allowed_amount=Decimal("200.00"),
        network_status="in_network",
        deductible_applicability=True,
        remaining_deductible=Decimal(0),
        copay=Decimal("30.00"),
        coinsurance_rate=Decimal("0.20"),
        copay_interaction="unknown",
        remaining_oop_max=Decimal("1000.00"),
    )
    assert result.low.to_decimal() < result.high.to_decimal()
    assert "copay_interaction" in result.unknowns


def test_out_of_network_not_capped_at_allowed_amount():
    # A pathological coinsurance_rate > 1 (caller-defined OON semantics) must
    # not be silently clamped back down to the allowed amount.
    result = out_of_pocket_estimate(
        allowed_amount=Decimal("200.00"),
        network_status="out_of_network",
        deductible_applicability=True,
        remaining_deductible=Decimal(0),
        copay=Decimal(0),
        coinsurance_rate=Decimal("1.5"),
        copay_interaction="in_addition",
        remaining_oop_max=None,
    )
    assert result.high.to_decimal() == Decimal("300.00")
    assert any("out-of-network" in w.lower() for w in result.warnings)


def test_in_network_always_capped_at_allowed_amount():
    result = out_of_pocket_estimate(
        allowed_amount=Decimal("200.00"),
        network_status="in_network",
        deductible_applicability=True,
        remaining_deductible=Decimal(0),
        copay=Decimal(0),
        coinsurance_rate=Decimal("1.5"),
        copay_interaction="in_addition",
        remaining_oop_max=None,
    )
    assert result.high.to_decimal() == Decimal("200.00")
