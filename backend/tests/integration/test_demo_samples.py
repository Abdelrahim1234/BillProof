"""Each sample bill exists to demonstrate one honest outcome. If a sample stops
showing what it promises -- because prices or scoring moved -- these fail.
"""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run_seed():
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "seed.py")],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def _analyze(client, sample: str | None = None):
    _run_seed()
    body = {} if sample is None else {"sample": sample}
    created = client.post("/api/v1/demo/cases", json=body).json()["data"]
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    analysis = client.post(f"/api/v1/cases/{created['case_id']}/analysis", headers=headers).json()
    return created, analysis["data"], headers


def test_catalogue_lists_every_sample(client):
    data = client.get("/api/v1/demo/samples").json()["data"]
    ids = [s["id"] for s in data]
    assert ids[0] == "insured_visit"
    assert set(ids) >= {
        "insured_visit",
        "uninsured_emergency",
        "carilion_emergency",
        "uninsured_imaging",
        "full_itemized",
        "insured_no_eob",
        "fair_bill",
        "bill_with_problems",
        "nothing_to_compare",
    }
    for sample in data:
        assert sample["title"] and sample["blurb"]
        assert sample["line_count"] >= 1


def test_default_body_still_loads_the_original_bill(client):
    created, analysis, _ = _analyze(client)
    assert created["is_demo"] is True
    assert created["sample"] == "insured_visit"
    assert len(analysis["line_comparisons"]) == 3


def test_emergency_sample_scores_every_line_against_cash_prices(client):
    _, analysis, _ = _analyze(client, "uninsured_emergency")
    scored = [c for c in analysis["line_comparisons"] if c["review_score"] is not None]
    assert len(scored) == 3
    for comparison in scored:
        assert comparison["benchmark"]["basis"] == "hospital_discounted_cash"
        assert comparison["difference"]["amount_cents"] > 0
        assert comparison["references"], "a scored line must carry its source"


def test_imaging_sample_compares_against_that_hospitals_own_price(client):
    _, analysis, _ = _analyze(client, "uninsured_imaging")
    (comparison,) = analysis["line_comparisons"]
    assert comparison["comparison_status"] == "compared"
    # Carilion's published cash price for 74177, not LewisGale's.
    assert comparison["benchmark"]["median"]["amount_cents"] == 154210


def test_fair_bill_sample_does_not_manufacture_a_gap(client):
    _, analysis, _ = _analyze(client, "fair_bill")
    for comparison in analysis["line_comparisons"]:
        assert comparison["review_score"] == 0
        assert comparison["review_label"] == "limited_discrepancy_signal"
        assert comparison["difference"]["amount_cents"] < 0


def test_problem_sample_raises_findings_that_need_no_price(client):
    _, analysis, _ = _analyze(client, "bill_with_problems")
    kinds = {f["finding_type"] for f in analysis["non_price_findings"]}
    assert {"exact_duplicate_line", "missing_code", "unknown_care_setting"} <= kinds


def test_unpriced_sample_declines_to_score(client):
    _, analysis, _ = _analyze(client, "nothing_to_compare")
    assert analysis["status"] == "insufficient_data"
    for comparison in analysis["line_comparisons"]:
        assert comparison["comparison_status"] == "insufficient_data"
        assert comparison["review_score"] is None


def test_insured_without_an_eob_refuses_to_compare_what_you_owe(client):
    """docs/03: patient responsibility is never compared with a negotiated rate."""
    _, analysis, _ = _analyze(client, "insured_no_eob")
    for comparison in analysis["line_comparisons"]:
        assert comparison["comparison_status"] == "compared"
        assert comparison["review_score"] is None
        assert comparison["difference"] is None
        assert comparison["comparison_subject"] is None
        assert comparison["benchmark"]["basis"] == "hospital_discounted_cash_anchor"
        assert any("EOB" in q for q in comparison["suggested_questions"])


def test_the_two_hospitals_are_priced_from_their_own_files(client):
    """The same ER code at each hospital must cite that hospital's own price."""
    _, lewisgale, _ = _analyze(client, "full_itemized")
    _, carilion, _ = _analyze(client, "carilion_emergency")

    def er_benchmark(analysis):
        for c in analysis["line_comparisons"]:
            median = (c["benchmark"] or {}).get("median") if c["review_score"] is not None else None
            if median and median["amount_cents"] in (313500, 76230):
                return median["amount_cents"]
        return None

    assert er_benchmark(lewisgale) == 313500  # LewisGale level 4 ER cash price
    assert er_benchmark(carilion) == 76230  # Carilion's, for the identical code


def test_full_itemized_sample_mixes_priced_and_unpriceable_lines(client):
    _, analysis, _ = _analyze(client, "full_itemized")
    statuses = [c["comparison_status"] for c in analysis["line_comparisons"]]
    assert len(statuses) == 6
    assert statuses.count("insufficient_data") == 2, "the unpriced lines must stay unpriced"
    assert analysis["status"] == "partial"


@pytest.mark.parametrize("bad", ["../demo_bill_expected", "nope", "a/b"])
def test_unknown_sample_is_rejected(client, bad):
    _run_seed()
    response = client.post("/api/v1/demo/cases", json={"sample": bad})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNKNOWN_SAMPLE"


def test_every_sample_is_flagged_synthetic_in_its_packet(client):
    for sample in ["uninsured_emergency", "bill_with_problems"]:
        created, _, headers = _analyze(client, sample)
        packet = client.post(
            f"/api/v1/cases/{created['case_id']}/packet",
            headers=headers,
            json={"goal": "billing_review", "language": "en"},
        ).json()["data"]
        assert packet["packet"]["bill_is_synthetic"] is True
        assert "synthetic" in packet["packet"]["bill_notice"].lower()
