import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ROOM = "vthacks"


def _run_seed():
    # conftest drops and recreates the schema per test, so each test that needs
    # seeded hospitals reseeds, matching the other integration suites.
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "seed.py")],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def _analyzed_demo_case(client):
    _run_seed()
    created = client.post("/api/v1/demo/cases").json()["data"]
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    client.post(f"/api/v1/cases/{created['case_id']}/analysis", headers=headers)
    return created["case_id"], headers


def test_empty_room_returns_null(client):
    assert client.get(f"/api/v1/screens/{ROOM}/latest").json()["data"] is None


def test_publish_then_screen_sees_the_comparison(client):
    case_id, headers = _analyzed_demo_case(client)

    published = client.post(
        f"/api/v1/cases/{case_id}/publish", headers=headers, json={"room_code": ROOM}
    )
    assert published.status_code == 200

    data = client.get(f"/api/v1/screens/{ROOM}/latest").json()["data"]
    assert data["source_label"] == "example_bill"
    assert data["is_demo_bill"] is True
    assert data["hospital_name"] == "LewisGale Hospital Montgomery"
    assert data["analysis"]["status"] == "partial"
    assert len(data["lines"]) == len(data["analysis"]["line_comparisons"])
    # The screen payload carries display labels and numbers, never a token.
    assert "access_token" not in str(data)


def test_room_code_is_case_insensitive(client):
    case_id, headers = _analyzed_demo_case(client)
    client.post(f"/api/v1/cases/{case_id}/publish", headers=headers, json={"room_code": "VTHacks"})
    assert client.get("/api/v1/screens/vthacks/latest").json()["data"] is not None


def test_publishing_replaces_the_previous_bill(client):
    first_case, first_headers = _analyzed_demo_case(client)
    client.post(f"/api/v1/cases/{first_case}/publish", headers=first_headers, json={"room_code": ROOM})

    second_case, second_headers = _analyzed_demo_case(client)
    client.post(
        f"/api/v1/cases/{second_case}/publish", headers=second_headers, json={"room_code": ROOM}
    )

    data = client.get(f"/api/v1/screens/{ROOM}/latest").json()["data"]
    assert data["analysis"]["case_id"] == second_case


def test_publish_requires_a_matching_token(client):
    case_id, _ = _analyzed_demo_case(client)
    other = client.post("/api/v1/demo/cases").json()["data"]

    missing = client.post(f"/api/v1/cases/{case_id}/publish", json={"room_code": ROOM})
    assert missing.status_code == 401

    wrong = client.post(
        f"/api/v1/cases/{case_id}/publish",
        headers={"Authorization": f"Bearer {other['access_token']}"},
        json={"room_code": ROOM},
    )
    assert wrong.status_code == 403


def test_publish_without_analysis_is_rejected(client):
    _run_seed()
    created = client.post("/api/v1/demo/cases").json()["data"]
    response = client.post(
        f"/api/v1/cases/{created['case_id']}/publish",
        headers={"Authorization": f"Bearer {created['access_token']}"},
        json={"room_code": ROOM},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ANALYSIS_REQUIRED"


def test_bad_room_codes_are_rejected(client):
    case_id, headers = _analyzed_demo_case(client)
    for bad in ["ab", "room code", "room/code", "x" * 33]:
        response = client.post(
            f"/api/v1/cases/{case_id}/publish", headers=headers, json={"room_code": bad}
        )
        assert response.status_code == 422, bad


def test_clearing_a_room_empties_the_screen(client):
    case_id, headers = _analyzed_demo_case(client)
    client.post(f"/api/v1/cases/{case_id}/publish", headers=headers, json={"room_code": ROOM})

    assert client.delete(f"/api/v1/screens/{ROOM}").status_code == 204
    assert client.get(f"/api/v1/screens/{ROOM}/latest").json()["data"] is None


def test_hand_typed_description_never_reaches_the_wall(client):
    created = client.post("/api/v1/cases", json={"coverage_type": "uninsured"}).json()["data"]
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    client.post(
        f"/api/v1/cases/{created['case_id']}/bill/manual",
        headers=headers,
        json={
            "lines": [
                {
                    "code": "71046",
                    "code_type": "CPT",
                    "description": "X-ray for Jane Doe, jane@example.com, 555-123-4567",
                    "billed_amount": "450.00",
                }
            ]
        },
    )
    client.post(f"/api/v1/cases/{created['case_id']}/analysis", headers=headers)
    client.post(
        f"/api/v1/cases/{created['case_id']}/publish", headers=headers, json={"room_code": ROOM}
    )

    data = client.get(f"/api/v1/screens/{ROOM}/latest").json()["data"]
    # A projector is not the place for anything a person typed themselves: no
    # regex catches a name, so the description is dropped and the code stands in.
    assert data["lines"][0]["description"] is None
    assert data["lines"][0]["code"] == "71046"
    assert "Jane Doe" not in str(data)
    assert "jane@example.com" not in str(data)


def test_the_example_bill_keeps_its_descriptions(client):
    case_id, headers = _analyzed_demo_case(client)
    client.post(f"/api/v1/cases/{case_id}/publish", headers=headers, json={"room_code": ROOM})

    data = client.get(f"/api/v1/screens/{ROOM}/latest").json()["data"]
    descriptions = [line["description"] for line in data["lines"]]
    assert "Chest X-ray, 2 views" in descriptions
