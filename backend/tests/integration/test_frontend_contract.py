import asyncio
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from billproof import store
from billproof.models import Case, FacilitySource, PriceRecord, ScreenSubmission
from billproof.repositories import hospitals as hospitals_repo
from billproof.repositories import prices as prices_repo
from billproof.services.case_auth import hash_token
from billproof.services.privacy import find_sas_leak

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_seed() -> None:
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "seed.py")],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def _facility_id(name: str) -> str:
    async def get_id() -> str:
        facility = await hospitals_repo.get_facility_by_name(store.get_public_db(), name)
        assert facility is not None
        return facility.id

    return asyncio.run(get_id())


def test_public_hospital_contract_is_active_nrv_market_only(client):
    _run_seed()
    response = client.get("/api/v1/hospitals")
    assert response.status_code == 200
    rows = response.json()["data"]
    assert {row["name"] for row in rows} == {
        "LewisGale Hospital Montgomery",
        "Carilion New River Valley Medical Center",
    }

    inova_id = _facility_id("Inova Fairfax Hospital")
    assert client.get(f"/api/v1/hospitals/{inova_id}").status_code == 404
    assert client.post(
        "/api/v1/cases", json={"hospital_id": inova_id, "coverage_type": "uninsured"}
    ).status_code == 404

    async def insert_legacy_case() -> None:
        await store.get_private_db()["cases"].insert_one(
            Case(
                id="legacy-inactive-case",
                access_token_hash=hash_token("legacy-token"),
                hospital_id=inova_id,
                coverage_type="uninsured",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ).to_doc()
        )

    asyncio.run(insert_legacy_case())
    legacy = client.get(
        "/api/v1/cases/legacy-inactive-case",
        headers={"Authorization": "Bearer legacy-token"},
    )
    assert legacy.status_code == 403
    assert legacy.json()["error"]["code"] == "CASE_OUTSIDE_ACTIVE_MARKET"

    deleted = client.delete(
        "/api/v1/cases/legacy-inactive-case",
        headers={"Authorization": "Bearer legacy-token"},
    )
    assert deleted.status_code == 204

    async def legacy_case_was_purged() -> bool:
        return await store.get_private_db()["cases"].find_one({"_id": "legacy-inactive-case"}) is None

    assert asyncio.run(legacy_case_was_purged())


def test_price_search_shape_and_evidence_guards(client):
    _run_seed()
    hospital_id = _facility_id("LewisGale Hospital Montgomery")

    response = client.get(
        "/api/v1/prices/search",
        params={"hospital_id": hospital_id, "code": "71046", "charge_type": "discounted_cash"},
    )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows
    assert {"code", "code_type", "description"}.issubset(rows[0])
    assert all(row["is_synthetic"] is False for row in rows)
    assert find_sas_leak(response.json()) is None
    assert all("?" not in row["source"]["source_url"] for row in rows)

    async def insert_ineligible_rows() -> None:
        db = store.get_public_db()
        verified = (await prices_repo.search_prices(db, hospital_id=hospital_id, code="71046"))[0]
        await prices_repo.upsert(
            db,
            verified.model_copy(
                update={
                    "id": "synthetic-runtime-guard",
                    "code": "77777",
                    "is_synthetic": True,
                    "source_record_locator": "/synthetic",
                }
            ),
        )
        inactive_url = "https://example.test/inactive.json"
        await hospitals_repo.upsert_facility_source(
            db,
            FacilitySource(
                hospital_id=hospital_id,
                source_type="retired",
                source_url=inactive_url,
                file_date=date.today(),
                sha256="b" * 64,
                active=False,
            ),
        )
        await prices_repo.upsert(
            db,
            PriceRecord(
                id="inactive-runtime-guard",
                hospital_id=hospital_id,
                code_type="CPT",
                code="77778",
                description="Inactive source row",
                care_setting="outpatient",
                charge_type="discounted_cash",
                amount=Decimal("1.00"),
                source_url=inactive_url,
                source_record_locator="/inactive",
                source_type="retired",
                is_synthetic=False,
            ),
        )

    asyncio.run(insert_ineligible_rows())
    assert client.get("/api/v1/prices/search", params={"hospital_id": hospital_id, "code": "77777"}).json()[
        "data"
    ] == []
    assert client.get("/api/v1/prices/search", params={"hospital_id": hospital_id, "code": "77778"}).json()[
        "data"
    ] == []


def test_hero_demo_has_opposite_real_price_conclusions(client):
    _run_seed()
    samples = client.get("/api/v1/demo/samples")
    assert samples.status_code == 200
    assert samples.json()["data"][0]["id"] == "nrv_cash_review"

    created = client.post("/api/v1/demo/cases", json={"sample": "nrv_cash_review"})
    assert created.status_code == 201
    case = created.json()["data"]
    headers = {"Authorization": f"Bearer {case['access_token']}"}
    lines = client.get(f"/api/v1/cases/{case['case_id']}/bill", headers=headers).json()["data"]
    by_id = {line["id"]: line for line in lines}

    response = client.post(f"/api/v1/cases/{case['case_id']}/analysis", headers=headers)
    assert response.status_code == 200
    comparisons = {
        by_id[item["line_id"]]["code"]: item for item in response.json()["data"]["line_comparisons"]
    }
    assert comparisons["80053"]["direction"] == "above"
    assert comparisons["80053"]["difference"]["amount_cents"] == 52559
    assert comparisons["71046"]["direction"] == "below"
    assert comparisons["71046"]["difference"]["amount_cents"] == -8700
    for item in comparisons.values():
        assert item["comparison_status"] == "compared"
        assert item["references"]
        assert all(reference["is_synthetic"] is False for reference in item["references"])


def test_screen_copy_is_token_free_and_drops_user_free_text(client):
    _run_seed()
    hospital_id = _facility_id("LewisGale Hospital Montgomery")
    created = client.post(
        "/api/v1/cases", json={"hospital_id": hospital_id, "coverage_type": "uninsured"}
    ).json()["data"]
    case_id = created["case_id"]
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    manual = client.post(
        f"/api/v1/cases/{case_id}/bill/manual",
        headers=headers,
        json={
            "lines": [
                {
                    "code": "80053",
                    "code_type": "CPT",
                    "description": "User-entered private description",
                    "care_setting": "outpatient",
                    "billed_amount": "1385.59",
                }
            ]
        },
    )
    assert manual.status_code == 200
    assert client.post(f"/api/v1/cases/{case_id}/analysis", headers=headers).status_code == 200

    published = client.post(
        f"/api/v1/cases/{case_id}/publish",
        headers=headers,
        json={"room_code": "contract-room"},
    )
    assert published.status_code == 200
    assert client.post(
        f"/api/v1/cases/{case_id}/publish",
        headers=headers,
        json={"room_code": "short"},
    ).status_code == 422
    latest = client.get("/api/v1/screens/contract-room/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert "access_token" not in str(body)
    assert "case_id" not in str(body)
    assert "analysis_id" not in str(body)
    assert body["data"]["analysis"]["line_comparisons"][0]["references"][0]["price_record_id"] is None
    assert body["data"]["lines"][0]["id"] == "display-line-1"
    assert body["data"]["analysis"]["line_comparisons"][0]["line_id"] == "display-line-1"
    assert body["data"]["source_label"] == "own_bill"
    assert body["data"]["lines"][0]["description"] is None

    assert client.delete("/api/v1/screens/contract-room").status_code == 204
    assert client.get("/api/v1/screens/contract-room/latest").json()["data"] is None


def test_expired_screen_copy_is_never_publicly_readable(client):
    async def insert_expired_copy() -> None:
        await store.get_private_db()["screen_submissions"].insert_one(
            ScreenSubmission(
                case_id="expired-case",
                room_code="expired-room",
                source_label="example_bill",
                coverage_type="uninsured",
                analysis_json={},
                lines_json=[],
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            ).to_doc()
        )

    asyncio.run(insert_expired_copy())
    response = client.get("/api/v1/screens/expired-room/latest")
    assert response.status_code == 200
    assert response.json()["data"] is None
