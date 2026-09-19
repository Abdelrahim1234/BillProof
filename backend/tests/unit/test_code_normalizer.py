from billproof.services.code_normalizer import normalize_code, normalize_payer


def test_five_digit_ambiguity_stays_cpt_hcpcs():
    result = normalize_code("71046")
    assert result.code_type == "CPT_HCPCS"


def test_hcpcs_level_ii_preserved():
    result = normalize_code("j1100")
    assert result.code_type == "HCPCS"
    assert result.code == "J1100"


def test_revenue_code_keeps_leading_zero():
    result = normalize_code("0450", "REVENUE")
    assert result.code_type == "REVENUE"
    assert result.code == "0450"


def test_revenue_code_zero_pads_short_input():
    result = normalize_code("450", "REVENUE")
    assert result.code == "0450"


def test_modifier_is_separated_from_base_code():
    result = normalize_code("71046-26")
    assert result.code == "71046"
    assert result.modifier == "26"


def test_declared_type_overrides_guessing():
    result = normalize_code("71046", "CPT")
    assert result.code_type == "CPT"


def test_normalize_payer_collapses_suffixes_and_case():
    assert normalize_payer("Cigna, Inc.") == normalize_payer("CIGNA")
