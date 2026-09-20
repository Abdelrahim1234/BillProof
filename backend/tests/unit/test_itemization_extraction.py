from decimal import Decimal

from billproof.services.extraction import parse_itemization_table

# Fabricated structure matching real HCA-family itemized statements (revenue
# code sections, DATE [CODE] UNITS DESCRIPTION $ AMOUNT rows) -- no real
# bill's data, invented figures only.
SAMPLE_ITEMIZATION = """Itemization of Hospital Services
REV CODE DATE HCPS UNITS DESCRIPTION AMOUNT
0112 - ROOM AND CARE
01/02/2026 2 ROOM AND CARE $ 4,200.00
Subtotal: $ 4,200.00
0272 - MED SURG SUPPLY/STERILE
01/02/2026 00000 3 GAUZE PAD STERILE 4X4IN $ 36.00
Subtotal: $ 36.00
0301 - LAB/CHEMISTRY
01/02/2026 080053 1 COMP METABOLIC PANEL $ 610.25
Subtotal: $ 610.25
0305 - LAB/HEMATOLOGY
01/02/2026 085027 2 CBC AUTOMATED $ 220.10
Subtotal: $ 220.10
"""


def test_parses_rows_with_and_without_codes():
    doc = parse_itemization_table(SAMPLE_ITEMIZATION)
    assert not doc.needs_manual_entry
    assert len(doc.lines) == 4

    room = doc.lines[0]
    assert room.code is None
    assert room.code_type == "UNKNOWN"
    assert room.billed_amount == 4200
    assert room.needs_manual_review is True

    supply = doc.lines[1]
    assert supply.code_raw == "00000"
    assert supply.code is None  # "00000" is the format's no-code placeholder, not a real code


def test_zero_padded_code_normalizes_to_five_digit_cpt_hcpcs():
    doc = parse_itemization_table(SAMPLE_ITEMIZATION)
    panel = next(line for line in doc.lines if "METABOLIC" in (line.description or ""))
    assert panel.code == "80053"
    assert panel.code_type == "CPT_HCPCS"  # undeclared system -- docs/03: never auto-CPT
    assert panel.billed_amount == Decimal("610.25")
    assert panel.needs_manual_review is False


def test_section_headers_and_subtotals_are_not_misread_as_line_items():
    doc = parse_itemization_table(SAMPLE_ITEMIZATION)
    descriptions = [line.description for line in doc.lines]
    assert not any(d and d.startswith("Subtotal") for d in descriptions)
    assert not any(d and "ROOM AND CARE" == d and d != "ROOM AND CARE" for d in descriptions)


def test_unrecognized_text_yields_needs_manual_entry():
    doc = parse_itemization_table("Not a bill at all, just some prose.")
    assert doc.needs_manual_entry
    assert doc.lines == []
