import subprocess
import sys
from pathlib import Path

from billproof.services.privacy import find_sas_leak

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_seed():
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "seed.py")],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_demo_case_analysis_produces_expected_mix(client):
    _run_seed()

    created = client.post("/api/v1/demo/cases")
    assert created.status_code == 201
    data = created.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    result = client.post(f"/api/v1/cases/{case_id}/analysis", headers=headers)
    assert result.status_code == 200
    body = result.json()["data"]

    assert body["status"] == "partial"
    comparisons = {c["line_id"]: c for c in body["line_comparisons"]}
    statuses = [c["comparison_status"] for c in comparisons.values()]
    assert statuses.count("insufficient_data") == 1
    assert statuses.count("compared") == 1
    assert statuses.count("context_only") == 1
    assert body["summary"] == {"compared": 1, "context_only": 1, "insufficient_data": 1, "total": 3}

    scored = [c for c in comparisons.values() if c["comparison_status"] == "compared"]
    contextual = [c for c in comparisons.values() if c["comparison_status"] == "context_only"]
    assert len(scored) == 1
    assert len(contextual) == 1
    assert scored[0]["match"]["payer_exact"] is True
    assert scored[0]["match"]["plan_exact"] is True
    assert scored[0]["benchmark"]["confidence"] == "high"
    # FIX_BACKEND.md Fix 5: with peer_percentile omitted, gap+documentation's
    # weights renormalize from 60/15 to 80/20 (sum to 100) so a maxed-out gap
    # at this line's 1.00 tier-1 confidence reaches 100, not the old
    # artificially-capped 75.
    assert scored[0]["review_score"] == 100
    assert scored[0]["score_components"] == {"available": ["gap", "documentation"], "omitted": ["peer"]}
    assert scored[0]["review_label"] == "high_review_opportunity"
    assert scored[0]["percent_above_benchmark"] == "117.88"
    assert all(not ref["is_synthetic"] for ref in scored[0]["references"])
    assert contextual[0]["benchmark"]["basis"] == "hospital_discounted_cash_anchor"
    assert all(not ref["is_synthetic"] for ref in contextual[0]["references"])

    latest = client.get(f"/api/v1/cases/{case_id}/analysis/latest", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["data"]["status"] == "partial"

    receipts = client.get(f"/api/v1/cases/{case_id}/activity", headers=headers)
    tool_names = {r["tool_name"] for r in receipts.json()["data"]}
    assert "analyze_case" in tool_names


def test_comparison_status_distinguishes_context_only_from_compared(client):
    """FIX_BACKEND.md Fix 1: a line with a subject and a benchmark but no
    scoreable pair (no difference, no score, no source-backed number) must be
    reported as context_only, not compared. Before the fix, the demo case's
    80053 line (billed amount only, no allowed amount -> cash-price anchor
    shown as context) was labeled "compared" alongside the one line that
    actually has a defensible difference and score -- producing a false
    "2 compared" count when only 1 is real."""
    _run_seed()

    created = client.post("/api/v1/demo/cases")
    data = created.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    result = client.post(f"/api/v1/cases/{case_id}/analysis", headers=headers)
    body = result.json()["data"]

    statuses = [c["comparison_status"] for c in body["line_comparisons"]]
    assert statuses.count("compared") == 1, "exactly one line has a real, source-backed difference and score"
    assert statuses.count("context_only") == 1, "the no-allowed-amount line has a subject/benchmark but no score"
    assert statuses.count("insufficient_data") == 1

    compared_lines = [c for c in body["line_comparisons"] if c["comparison_status"] == "compared"]
    for c in compared_lines:
        assert c["difference"] is not None
        assert c["review_score"] is not None
        assert c["references"], "a compared line must carry at least one source citation"

    context_only_lines = [c for c in body["line_comparisons"] if c["comparison_status"] == "context_only"]
    for c in context_only_lines:
        assert c["difference"] is None
        assert c["review_score"] is None

    assert body["summary"] == {"compared": 1, "context_only": 1, "insufficient_data": 1, "total": 3}


def test_uninsured_lewisgale_80053_line_produces_a_real_compared_result(client):
    """FIX_BACKEND.md Fix 7: the self-pay path is fully implemented but the
    uploaded-bill demo created an insured case, which never reaches it. This
    proves it against real seeded data: an uninsured case at LewisGale with
    an 80053 billed line must produce comparison_status="compared" with a
    non-null difference, score, and source citation against LewisGale's
    published $860.00 cash price."""
    _run_seed()

    hospitals = client.get("/api/v1/hospitals").json()["data"]
    lewisgale = next(h for h in hospitals if h["name"] == "LewisGale Hospital Montgomery")

    created = client.post("/api/v1/cases", json={"hospital_id": lewisgale["id"], "coverage_type": "uninsured"})
    data = created.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    client.post(
        f"/api/v1/cases/{case_id}/bill/manual",
        headers=headers,
        json={"lines": [{"code": "80053", "code_type": "CPT", "billed_amount": "1385.59"}]},
    )

    result = client.post(f"/api/v1/cases/{case_id}/analysis", headers=headers)
    assert result.status_code == 200
    body = result.json()["data"]

    assert len(body["line_comparisons"]) == 1
    line = body["line_comparisons"][0]
    assert line["comparison_status"] == "compared"
    assert line["benchmark"]["basis"] == "hospital_discounted_cash"
    assert line["benchmark"]["match_tier"]
    assert line["benchmark"]["confidence"] is not None
    assert line["difference"] is not None
    assert line["difference"]["amount_cents"] == 52559  # $1385.59 - $860.00
    assert line["percent_above_benchmark"] is not None
    assert line["review_score"] is not None
    assert line["review_label"] is not None
    assert line["match"] is not None
    assert line["match"]["hospital_exact"] is True
    assert line["references"], "a compared line must carry a source citation"
    assert line["references"][0]["source_url"]
    assert line["references"][0]["retrieval_date"]
    assert body["summary"] == {"compared": 1, "context_only": 0, "insufficient_data": 0, "total": 1}


def test_insufficient_bill_returns_insufficient_data_not_500(client):
    case = client.post("/api/v1/cases", json={"coverage_type": "unknown"})
    data = case.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    client.post(
        f"/api/v1/cases/{case_id}/bill/manual",
        headers=headers,
        json={"lines": [{"code": "00000", "code_type": "UNKNOWN", "billed_amount": "10.00"}]},
    )

    result = client.post(f"/api/v1/cases/{case_id}/analysis", headers=headers)
    assert result.status_code == 200
    assert result.json()["data"]["status"] == "insufficient_data"


def test_signed_retrieval_url_never_escapes(client):
    """CLAUDE_FINAL_DEMO_HARDENING_PROMPT Fix 2: recursively scans real live
    API responses -- not a mock -- for SAS parameters. Also asserts every
    source_url/citation_url in a real comparison carries no query string."""
    _run_seed()
    created = client.post("/api/v1/demo/cases")
    data = created.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    responses = [
        client.get("/api/v1/hospitals"),
        client.post(f"/api/v1/cases/{case_id}/analysis", headers=headers),
        client.get(f"/api/v1/cases/{case_id}/analysis/latest", headers=headers),
        client.post(
            f"/api/v1/cases/{case_id}/packet", headers=headers, json={"goal": "billing_review", "language": "en"}
        ),
        client.get(f"/api/v1/cases/{case_id}/activity", headers=headers),
    ]

    checked_a_url = False
    for resp in responses:
        assert resp.status_code == 200
        body = resp.json()
        leak_path = find_sas_leak(body)
        assert leak_path is None, f"SAS parameter found in response at {leak_path}"

        for c in body.get("data", {}).get("line_comparisons", []) if isinstance(body.get("data"), dict) else []:
            for ref in c.get("references", []):
                assert "?" not in ref["source_url"], "public source_url must carry no query string"
                checked_a_url = True

    assert checked_a_url, "test did not actually exercise a real reference -- update the fixture/flow above"
