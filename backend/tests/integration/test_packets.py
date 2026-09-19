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


def _demo_case_with_analysis(client):
    _run_seed()
    created = client.post("/api/v1/demo/cases").json()["data"]
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    case_id = created["case_id"]
    client.post(f"/api/v1/cases/{case_id}/analysis", headers=headers)
    return case_id, headers


def test_packet_requires_analysis_first(client):
    case = client.post("/api/v1/cases", json={"coverage_type": "uninsured"}).json()["data"]
    headers = {"Authorization": f"Bearer {case['access_token']}"}
    resp = client.post(
        f"/api/v1/cases/{case['case_id']}/packet",
        headers=headers,
        json={"goal": "billing_review", "language": "en"},
    )
    assert resp.status_code == 400


def test_english_and_spanish_packets_render(client):
    case_id, headers = _demo_case_with_analysis(client)

    en = client.post(
        f"/api/v1/cases/{case_id}/packet", headers=headers, json={"goal": "billing_review", "language": "en"}
    )
    assert en.status_code == 200
    en_body = en.json()["data"]
    assert "Bill review packet" in en_body["markdown"]
    assert "Educational information" in en_body["markdown"]
    assert en_body["packet"]["bill_is_synthetic"] is True
    assert "This patient bill is a synthetic fixture" in en_body["markdown"]
    assert "synthetic fixture, not a real hospital price" not in en_body["markdown"]
    assert "MRF last updated 2026-09-01" in en_body["markdown"]
    assert "The MRF jointly lists LewisGale Hospital Montgomery and Christiansburg FSER" in en_body["markdown"]
    assert "Most rows do not identify which listed location they apply to" in en_body["markdown"]
    assert "does not identify whether this is a facility or professional charge" in en_body["markdown"]
    assert "does not state a service unit" in en_body["markdown"]
    assert "/standard_charge_information/205871/" in en_body["markdown"]
    assert "/standard_charge_information/118225/" in en_body["markdown"]
    assert len(en_body["packet"]["benchmark_sources"]) == 2
    assert "$206.54 (your plan's disclosed negotiated rate)" in en_body["markdown"]
    assert "-- (context only)" in en_body["markdown"]
    assert len(en_body["packet"]["line_items"]) == 3

    es = client.post(
        f"/api/v1/cases/{case_id}/packet",
        headers=headers,
        json={"goal": "financial_assistance", "language": "es"},
    )
    assert es.status_code == 200
    es_body = es.json()["data"]
    assert "Paquete de revision" in es_body["markdown"]
    assert "asesoria legal" in es_body["markdown"]
    assert es_body["packet"]["bill_is_synthetic"] is True
    assert "Esta cuenta del paciente es un ejemplo sintetico" in es_body["markdown"]
    assert "MRF actualizado por ultima vez 2026-09-01" in es_body["markdown"]

    latest = client.get(f"/api/v1/cases/{case_id}/packet/latest", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["data"]["language"] == "es"


def test_user_entered_bill_does_not_get_demo_notice(client):
    _run_seed()
    hospital = client.get("/api/v1/hospitals", params={"name": "LewisGale"}).json()["data"][0]
    created = client.post(
        "/api/v1/cases",
        json={
            "hospital_id": hospital["id"],
            "coverage_type": "commercial",
            "payer_name": "Cigna",
            "plan_name": "NPR",
            "care_setting": "outpatient",
        },
    ).json()["data"]
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    client.post(
        f"/api/v1/cases/{created['case_id']}/bill/manual",
        headers=headers,
        json={
            "lines": [
                {
                    "code": "71046",
                    "code_type": "CPT",
                    "care_setting": "outpatient",
                    "billed_amount": "450.00",
                    "allowed_amount": "450.00",
                }
            ]
        },
    )
    client.post(f"/api/v1/cases/{created['case_id']}/analysis", headers=headers)
    response = client.post(
        f"/api/v1/cases/{created['case_id']}/packet",
        headers=headers,
        json={"goal": "billing_review", "language": "en"},
    )

    assert response.status_code == 200
    packet = response.json()["data"]
    assert packet["packet"]["bill_is_synthetic"] is False
    assert packet["packet"]["bill_notice"] is None
    assert "This patient bill is a synthetic fixture" not in packet["markdown"]


def test_no_wording_claims_illegal_or_guaranteed(client):
    case_id, headers = _demo_case_with_analysis(client)
    resp = client.post(
        f"/api/v1/cases/{case_id}/packet", headers=headers, json={"goal": "billing_review", "language": "en"}
    )
    markdown = resp.json()["data"]["markdown"].lower()
    for banned in ("illegal", "guaranteed savings", "fraud", "you broke the law"):
        assert banned not in markdown


def test_pdf_packet_returns_clean_501(client):
    case_id, headers = _demo_case_with_analysis(client)
    resp = client.get(f"/api/v1/cases/{case_id}/packet/latest.pdf", headers=headers)
    assert resp.status_code == 501
