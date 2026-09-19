import subprocess
import sys
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from billproof.db import SessionLocal
from billproof.mcp_server import mcp
from billproof.models import Facility

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


def _lewisgale_id() -> str:
    db = SessionLocal()
    try:
        f = db.query(Facility).filter_by(name="LewisGale Hospital Montgomery").one()
        return f.id
    finally:
        db.close()


async def test_handshake_and_list_tools():
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        await session.initialize()
        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        expected = {
            "find_hospital",
            "lookup_public_prices",
            "compare_bill_line",
            "analyze_case",
            "find_assistance_options",
            "build_negotiation_packet",
            "get_source_provenance",
            "find_nearby_facilities",
            "get_local_price_landscape",
            "estimate_plan_cost_share",
            "compare_area_prices",
            "add_map_evidence_to_case",
            "explain_price_source",
        }
        assert expected.issubset(names)
        for t in tools.tools:
            assert t.outputSchema is not None


async def test_proofmap_tools_find_and_explain(client):
    _run_seed()
    hospital_id = _lewisgale_id()

    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        await session.initialize()
        nearby = await session.call_tool(
            "find_nearby_facilities", {"lat": 37.2001, "lng": -80.4181, "radius_miles": 25}
        )
        assert nearby.isError is not True
        assert len(nearby.structuredContent["data"]) == 5

        landscape = await session.call_tool(
            "get_local_price_landscape",
            {"facility_id": hospital_id, "service_code": "71046", "code_type": "CPT"},
        )
        assert landscape.isError is not True
        assert len(landscape.structuredContent["data"]) > 0
        price_record_id_query = client.get(
            "/api/v1/prices/search", params={"hospital_id": hospital_id, "code": "71046"}
        )
        assert price_record_id_query.status_code == 200
        price_rows = price_record_id_query.json()["data"]
        negotiated = next(row for row in price_rows if row["charge_type"] == "payer_negotiated")
        provenance = await session.call_tool(
            "get_source_provenance", {"price_record_id": negotiated["price_record_id"]}
        )
        assert provenance.isError is not True
        assert provenance.structuredContent["data"]["sha256"] == (
            "a275b2d66ad697bebf47391c1130a1c123cadf2b49ec8e5696de919c9155767c"
        )
        assert provenance.structuredContent["data"]["schema_version"] == "3.0.0"
        assert provenance.structuredContent["data"]["source_record_locator"].endswith(
            "/payers_information/2/standard_charge_dollar"
        )

        cost_share = await session.call_tool(
            "estimate_plan_cost_share",
            {"allowed_amount": "200.00", "copay": "30.00", "coinsurance_rate": "0.20", "copay_interaction": "in_addition"},
        )
        assert cost_share.isError is not True
        assert cost_share.structuredContent["data"]["low"]["amount_cents"] == 7000


async def test_find_hospital_and_lookup_prices_return_typed_content():
    _run_seed()
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        await session.initialize()
        result = await session.call_tool("find_hospital", {"query": "LewisGale"})
        assert result.isError is not True
        assert result.structuredContent["data"]
        hospital_id = result.structuredContent["data"][0]["id"]

        prices = await session.call_tool(
            "lookup_public_prices",
            {"hospital_id": hospital_id, "code_type": "CPT", "code": "71046"},
        )
        assert prices.isError is not True
        assert len(prices.structuredContent["data"]) > 0
        assert prices.structuredContent["data"][0]["source"]["source_url"]
        assert prices.structuredContent["data"][0]["price_record_id"]
        assert prices.structuredContent["data"][0]["source_record_locator"]
        assert prices.structuredContent["data"][0]["is_synthetic"] is False


async def test_compare_bill_line_matches_rest_result(client):
    _run_seed()
    hospital_id = _lewisgale_id()

    case = client.post(
        "/api/v1/cases",
        json={
            "hospital_id": hospital_id,
            "coverage_type": "commercial",
            "payer_name": "Cigna",
            "plan_name": "NPR",
            "care_setting": "outpatient",
        },
    ).json()["data"]
    headers = {"Authorization": f"Bearer {case['access_token']}"}
    client.post(
        f"/api/v1/cases/{case['case_id']}/bill/manual",
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
    rest_result = client.post(f"/api/v1/cases/{case['case_id']}/analysis", headers=headers).json()["data"]
    rest_comparison = rest_result["line_comparisons"][0]

    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        await session.initialize()
        mcp_result = await session.call_tool(
            "compare_bill_line",
            {
                "hospital_id": hospital_id,
                "code_type": "CPT",
                "code": "71046",
                "comparison_amount": "450.00",
                "comparison_amount_type": "allowed_amount",
                "units": "1",
                "coverage_type": "commercial",
                "care_setting": "outpatient",
                "payer_name": "Cigna",
                "plan_name": "NPR",
            },
        )
    assert mcp_result.isError is not True
    mcp_comparison = mcp_result.structuredContent["data"]

    def strip_line_id(d):
        return {k: v for k, v in d.items() if k != "line_id"}

    assert strip_line_id(mcp_comparison) == strip_line_id(rest_comparison)


async def test_protected_tool_rejects_wrong_token(client):
    _run_seed()
    case = client.post("/api/v1/cases", json={"coverage_type": "uninsured"}).json()["data"]

    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        await session.initialize()
        result = await session.call_tool(
            "analyze_case", {"case_id": case["case_id"], "access_token": "wrong-token"}
        )
    assert result.isError is True


async def test_analyze_case_records_mcp_receipt(client):
    _run_seed()
    demo = client.post("/api/v1/demo/cases").json()["data"]

    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        await session.initialize()
        result = await session.call_tool(
            "analyze_case", {"case_id": demo["case_id"], "access_token": demo["access_token"]}
        )
    assert result.isError is not True

    headers = {"Authorization": f"Bearer {demo['access_token']}"}
    receipts = client.get(f"/api/v1/cases/{demo['case_id']}/activity", headers=headers).json()["data"]
    mcp_receipts = [r for r in receipts if r["transport"] == "mcp" and r["tool_name"] == "analyze_case"]
    assert len(mcp_receipts) == 1


async def test_methodology_resource_and_prompt():
    async with create_connected_server_and_client_session(mcp._mcp_server) as session:
        await session.initialize()
        resource = await session.read_resource("methodology://pricing-comparison")
        text = resource.contents[0].text
        assert "amount types" in text.lower()

        prompt = await session.get_prompt(
            "prepare_hospital_call",
            {"case_id": "c1", "access_token": "t1", "language": "en", "goal": "billing_review"},
        )
        assert "analyze_case" in prompt.messages[0].content.text
