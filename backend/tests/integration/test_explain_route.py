"""Route-level wiring for the AI explain/ask feature. Gemini is mocked --
never a real network call in the automated suite."""

from billproof.services import explain


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeModels:
    async def generate_content(self, **kwargs):
        return _FakeResponse("This is a mocked, plain-language explanation.")


class _FakeAio:
    models = _FakeModels()


class _FakeClient:
    def __init__(self, api_key):
        self.aio = _FakeAio()


def _patch_gemini(monkeypatch):
    monkeypatch.setattr(
        explain,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "explanation_provider": "gemini",
                "gemini_api_key": "test-only-key",
                "gemini_model": "test-model",
            },
        )(),
    )
    monkeypatch.setattr(explain.genai, "Client", _FakeClient)


def test_ask_requires_consent(client, monkeypatch):
    _patch_gemini(monkeypatch)
    created = client.post("/api/v1/cases", json={"coverage_type": "uninsured"})
    data = created.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}

    resp = client.post(f"/api/v1/cases/{data['case_id']}/ask", headers=headers, json={"question": "hi"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "EXTERNAL_PROCESSING_NOT_CONSENTED"


def test_ask_about_case_with_consent(client, monkeypatch):
    _patch_gemini(monkeypatch)
    created = client.post(
        "/api/v1/cases", json={"coverage_type": "uninsured", "external_processing_consent": True}
    )
    data = created.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    client.post(
        f"/api/v1/cases/{case_id}/bill/manual",
        headers=headers,
        json={"lines": [{"code": "71046", "code_type": "CPT", "billed_amount": "450.00"}]},
    )

    resp = client.post(f"/api/v1/cases/{case_id}/ask", headers=headers, json={"question": "What is this?"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["answer"] == "This is a mocked, plain-language explanation."
    assert body["model"]

    receipts = client.get(f"/api/v1/cases/{case_id}/activity", headers=headers).json()["data"]
    ask_receipts = [r for r in receipts if r["tool_name"] == "ask_case_question"]
    assert len(ask_receipts) == 1
    # The question/answer text itself must never be persisted in the receipt.
    assert "What is this?" not in ask_receipts[0]["summary"]
    assert "mocked" not in ask_receipts[0]["summary"]


def test_explain_line_with_consent(client, monkeypatch):
    _patch_gemini(monkeypatch)
    created = client.post(
        "/api/v1/cases", json={"coverage_type": "uninsured", "external_processing_consent": True}
    )
    data = created.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    case_id = data["case_id"]

    lines = client.post(
        f"/api/v1/cases/{case_id}/bill/manual",
        headers=headers,
        json={"lines": [{"code": "71046", "code_type": "CPT", "billed_amount": "450.00"}]},
    ).json()["data"]
    line_id = lines[0]["id"]

    resp = client.post(f"/api/v1/cases/{case_id}/lines/{line_id}/explain", headers=headers, json={})
    assert resp.status_code == 200
    assert resp.json()["data"]["answer"] == "This is a mocked, plain-language explanation."


def test_explain_line_wrong_case_is_not_found(client, monkeypatch):
    _patch_gemini(monkeypatch)
    case_a = client.post(
        "/api/v1/cases", json={"coverage_type": "uninsured", "external_processing_consent": True}
    ).json()["data"]
    case_b = client.post(
        "/api/v1/cases", json={"coverage_type": "uninsured", "external_processing_consent": True}
    ).json()["data"]

    line = client.post(
        f"/api/v1/cases/{case_a['case_id']}/bill/manual",
        headers={"Authorization": f"Bearer {case_a['access_token']}"},
        json={"lines": [{"code": "71046", "code_type": "CPT", "billed_amount": "450.00"}]},
    ).json()["data"][0]

    resp = client.post(
        f"/api/v1/cases/{case_b['case_id']}/lines/{line['id']}/explain",
        headers={"Authorization": f"Bearer {case_b['access_token']}"},
        json={},
    )
    assert resp.status_code == 404
