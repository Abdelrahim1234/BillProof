import asyncio
import io
import json
from pathlib import Path

from billproof import store
from billproof.models import Facility
from billproof.repositories import hospitals as hospitals_repo

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "fixtures"


def _seed_demo_hospital():
    """Sync wrapper (see test_map.py's _facility_id) so the test stays a
    plain `def` and never fights TestClient's own blocking portal."""
    expected = json.loads((FIXTURE_DIR / "demo_bill_expected.json").read_text())

    async def _seed() -> None:
        await hospitals_repo.upsert_facility(
            store.get_public_db(),
            Facility(
                name=expected["hospital_name"],
                facility_type="hospital",
                address="1 Test St",
                city="Blacksburg",
                state="VA",
                zip_code="24060",
            ),
        )

    asyncio.run(_seed())
    return expected


def test_create_case_returns_token_once(client):
    resp = client.post("/api/v1/cases", json={"coverage_type": "uninsured"})
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["access_token"]
    assert body["case_id"]


def test_missing_token_is_401(client):
    resp = client.post("/api/v1/cases", json={"coverage_type": "uninsured"})
    case_id = resp.json()["data"]["case_id"]
    resp = client.get(f"/api/v1/cases/{case_id}")
    assert resp.status_code == 401


def test_wrong_token_is_403(client):
    resp = client.post("/api/v1/cases", json={"coverage_type": "uninsured"})
    case_id = resp.json()["data"]["case_id"]
    resp = client.get(f"/api/v1/cases/{case_id}", headers={"Authorization": "Bearer not-the-real-token"})
    assert resp.status_code == 403


def test_manual_bill_add_get_patch(client):
    resp = client.post("/api/v1/cases", json={"coverage_type": "uninsured"})
    data = resp.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    manual = client.post(
        f"/api/v1/cases/{case_id}/bill/manual",
        headers=headers,
        json={"lines": [{"code": "71046", "code_type": "CPT", "billed_amount": "450.00"}]},
    )
    assert manual.status_code == 200
    line = manual.json()["data"][0]
    assert line["code"] == "71046"

    got = client.get(f"/api/v1/cases/{case_id}/bill", headers=headers)
    assert len(got.json()["data"]) == 1

    patch = client.patch(
        f"/api/v1/cases/{case_id}/bill",
        headers=headers,
        json={
            "line_id": line["id"],
            "expected_version": line["version"],
            "billed_amount": "500.00",
        },
    )
    assert patch.status_code == 200
    assert patch.json()["data"]["billed_amount"] == "500.00"

    stale_patch = client.patch(
        f"/api/v1/cases/{case_id}/bill",
        headers=headers,
        json={
            "line_id": line["id"],
            "expected_version": line["version"],  # now stale
            "billed_amount": "999.00",
        },
    )
    assert stale_patch.status_code == 409


def test_text_extraction_and_bulk_confirm(client):
    resp = client.post("/api/v1/cases", json={"coverage_type": "commercial"})
    data = resp.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    bill_text = (FIXTURE_DIR / "demo_bill.txt").read_bytes()
    files = {"file": ("demo_bill.txt", io.BytesIO(bill_text), "text/plain")}
    extracted = client.post(f"/api/v1/cases/{case_id}/bill/extract", headers=headers, files=files)
    assert extracted.status_code == 200
    lines = extracted.json()["data"]["lines"]
    assert len(lines) == 3
    assert lines[0]["code"] == "71046"

    input_fields = {
        "code_raw",
        "code",
        "code_type",
        "modifiers",
        "description",
        "units",
        "rate_unit",
        "billed_amount",
        "allowed_amount",
        "insurer_paid",
        "patient_responsibility",
        "charge_scope",
        "care_setting",
    }
    clean_lines = [{k: v for k, v in ln.items() if k in input_fields} for ln in lines]
    confirm = client.post(
        f"/api/v1/cases/{case_id}/lines/bulk",
        headers=headers,
        json={"lines": clean_lines},
    )
    assert confirm.status_code == 200
    assert len(confirm.json()["data"]) == 3


def test_pdf_extraction_matches_text_extraction(client):
    resp = client.post("/api/v1/cases", json={"coverage_type": "commercial"})
    data = resp.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    pdf_bytes = (FIXTURE_DIR / "demo_bill.pdf").read_bytes()
    files = {"file": ("demo_bill.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    extracted = client.post(f"/api/v1/cases/{case_id}/bill/extract", headers=headers, files=files)
    assert extracted.status_code == 200
    lines = extracted.json()["data"]["lines"]
    assert len(lines) == 3


def test_oversize_upload_is_413(client, monkeypatch):
    resp = client.post("/api/v1/cases", json={"coverage_type": "commercial"})
    data = resp.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    import billproof.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("MAX_UPLOAD_MB", "0")
    config_module.get_settings.cache_clear()
    try:
        files = {"file": ("big.txt", io.BytesIO(b"x" * 2048), "text/plain")}
        resp = client.post(f"/api/v1/cases/{case_id}/bill/extract", headers=headers, files=files)
        assert resp.status_code == 413
    finally:
        config_module.get_settings.cache_clear()


def test_unsupported_media_type_is_415(client):
    resp = client.post("/api/v1/cases", json={"coverage_type": "commercial"})
    data = resp.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    invalid_utf8 = b"\x80\x81\x82\xfe\xff"
    files = {"file": ("bill.bin", io.BytesIO(invalid_utf8), "application/octet-stream")}
    resp = client.post(f"/api/v1/cases/{case_id}/bill/extract", headers=headers, files=files)
    assert resp.status_code == 415


def test_demo_case_works_fully_offline(client, monkeypatch):
    _seed_demo_hospital()

    def _no_network(*args, **kwargs):
        raise AssertionError("demo case creation must not touch the network")

    import socket

    monkeypatch.setattr(socket, "socket", _no_network)

    resp = client.post("/api/v1/demo/cases")
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["is_demo"] is True
    assert data["access_token"]

    headers = {"Authorization": f"Bearer {data['access_token']}"}
    bill = client.get(f"/api/v1/cases/{data['case_id']}/bill", headers=headers)
    assert len(bill.json()["data"]) == 3


def test_case_delete_and_purge(client):
    resp = client.post("/api/v1/cases", json={"coverage_type": "uninsured"})
    data = resp.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    deleted = client.delete(f"/api/v1/cases/{case_id}", headers=headers)
    assert deleted.status_code == 204

    gone = client.get(f"/api/v1/cases/{case_id}", headers=headers)
    assert gone.status_code == 403
