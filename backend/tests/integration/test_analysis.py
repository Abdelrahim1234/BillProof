import subprocess
import sys
from pathlib import Path

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
    assert statuses.count("compared") == 2

    scored = [c for c in comparisons.values() if c["comparison_status"] == "compared" and c["review_score"] is not None]
    contextual = [c for c in comparisons.values() if c["comparison_status"] == "compared" and c["review_score"] is None]
    assert len(scored) == 1
    assert len(contextual) == 1
    assert scored[0]["match"]["payer_exact"] is True
    assert scored[0]["match"]["plan_exact"] is True
    assert scored[0]["benchmark"]["confidence"] == "high"
    assert scored[0]["review_score"] == 75
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
