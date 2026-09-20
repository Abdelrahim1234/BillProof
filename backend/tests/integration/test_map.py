import asyncio
import subprocess
import sys
from pathlib import Path

from billproof import store
from billproof.repositories import hospitals as hospitals_repo

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


def _facility_id(name: str) -> str:
    """Sync wrapper: these tests are plain `def`s driving the sync TestClient,
    so this runs its own short-lived event loop rather than making every
    caller async (and fighting TestClient's own blocking portal)."""

    async def _get() -> str:
        facility = await hospitals_repo.get_facility_by_name(store.get_public_db(), name)
        return facility.id

    return asyncio.run(_get())


def test_map_search_returns_facilities_within_radius(client):
    _run_seed()
    resp = client.get("/api/v1/map/search", params={"lat": 37.2001, "lng": -80.4181, "radius_miles": 25})
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 2  # the two facilities in nrv_core_v1
    distances = [r["distance_miles"] for r in rows]
    assert distances == sorted(distances)


def test_map_search_radius_boundary_excludes_far_facilities(client):
    _run_seed()
    resp = client.get("/api/v1/map/search", params={"lat": 37.2001, "lng": -80.4181, "radius_miles": 0.001})
    rows = resp.json()["data"]
    assert len(rows) == 1  # only the point itself (LewisGale's own coordinates)


def test_map_legend_has_all_layers(client):
    resp = client.get("/api/v1/map/legend")
    layers = {row["layer"] for row in resp.json()["data"]}
    assert {"published_cash", "your_plan", "observed_public_payments", "assistance", "data_gaps"} == layers


def test_facility_price_evidence_exact_and_unavailable(client):
    _run_seed()
    lewisgale_id = _facility_id("LewisGale Hospital Montgomery")
    resp = client.get(
        f"/api/v1/facilities/{lewisgale_id}/price-evidence",
        params={"service_code": "71046", "code_type": "CPT"},
    )
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) > 0
    assert all(item["facility_id"] == lewisgale_id for item in items)
    assert all(item["source"]["source_url"] for item in items)
    assert all(item["confidence"] == "medium" for item in items)
    assert all(any("service unit" in warning for warning in item["limitations"]) for item in items)
    assert all(any("facility or professional" in warning for warning in item["limitations"]) for item in items)

    search = client.get(
        "/api/v1/map/search",
        params={
            "lat": 37.2001,
            "lng": -80.4181,
            "radius_miles": 25,
            "service_code": "71046",
            "code_type": "CPT",
        },
    )
    lewisgale_result = next(row for row in search.json()["data"] if row["id"] == lewisgale_id)
    assert lewisgale_result["evidence_availability"] == "partial"

    no_price_id = _facility_id("Carilion New River Valley Medical Center")
    empty = client.get(
        f"/api/v1/facilities/{no_price_id}/price-evidence",
        params={"service_code": "99999", "code_type": "CPT"},
    )
    assert empty.status_code == 200
    assert empty.json()["data"] == []  # active facility remains visible even with no matching evidence


def test_out_of_pocket_estimate_endpoint(client):
    resp = client.post(
        "/api/v1/estimates/out-of-pocket",
        json={
            "allowed_amount": "200.00",
            "network_status": "in_network",
            "deductible_applicability": True,
            "remaining_deductible": "0",
            "copay": "30.00",
            "coinsurance_rate": "0.20",
            "copay_interaction": "in_addition",
            "remaining_oop_max": "1000.00",
        },
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["low"]["amount_cents"] == 7000
    assert body["high"]["amount_cents"] == 7000


def test_add_and_remove_case_evidence_invalidates_packet(client):
    _run_seed()
    lewisgale_id = _facility_id("LewisGale Hospital Montgomery")
    demo = client.post("/api/v1/demo/cases").json()["data"]
    headers = {"Authorization": f"Bearer {demo['access_token']}"}
    case_id = demo["case_id"]

    client.post(f"/api/v1/cases/{case_id}/analysis", headers=headers)
    packet = client.post(
        f"/api/v1/cases/{case_id}/packet", headers=headers, json={"goal": "billing_review", "language": "en"}
    )
    assert packet.status_code == 200

    added = client.post(
        f"/api/v1/cases/{case_id}/evidence", headers=headers, json={"facility_id": lewisgale_id}
    )
    assert added.status_code == 200
    evidence_id = added.json()["data"]["id"]

    latest_packet = client.get(f"/api/v1/cases/{case_id}/packet/latest", headers=headers)
    assert latest_packet.status_code == 404  # invalidated, must be rebuilt

    removed = client.delete(f"/api/v1/cases/{case_id}/evidence/{evidence_id}", headers=headers)
    assert removed.status_code == 204
