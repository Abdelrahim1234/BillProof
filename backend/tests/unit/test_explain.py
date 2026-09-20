"""services/explain.py: gated on consent, never invents a number, never
makes a real network call in the automated suite (Gemini is mocked)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from billproof import models
from billproof.errors import AppError
from billproof.services import explain


def _case(**overrides) -> models.Case:
    defaults = {
        "access_token_hash": "x" * 64,
        "coverage_type": "uninsured",
        "language": "en",
        "expires_at": datetime.now(UTC) + timedelta(days=1),
        "external_processing_consent": True,
    }
    defaults.update(overrides)
    return models.Case(**defaults)


def _line(**overrides) -> models.BillLine:
    defaults = {"case_id": "case-1", "code": "71046", "code_type": "CPT", "billed_amount": Decimal("450.00")}
    defaults.update(overrides)
    return models.BillLine(**defaults)


class _FakeResponse:
    def __init__(self, text: str | None):
        self.text = text


class _FakeModels:
    def __init__(self, text: str | None, capture: dict):
        self._text = text
        self._capture = capture

    async def generate_content(self, *, model, contents, config):
        self._capture["model"] = model
        self._capture["contents"] = contents
        self._capture["config"] = config
        return _FakeResponse(self._text)


class _FakeAio:
    def __init__(self, text: str | None, capture: dict):
        self.models = _FakeModels(text, capture)


class _FakeClient:
    def __init__(self, text: str | None, capture: dict):
        self.aio = _FakeAio(text, capture)


def _patch_gemini(monkeypatch, text: str | None = "A plain-language explanation."):
    capture: dict = {}
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
    monkeypatch.setattr(explain.genai, "Client", lambda api_key: _FakeClient(text, capture))
    return capture


async def test_explain_line_requires_consent(monkeypatch):
    _patch_gemini(monkeypatch)
    case = _case(external_processing_consent=False)
    line = _line()

    with pytest.raises(AppError) as exc_info:
        await explain.explain_line(case, line, None, "why?")
    assert exc_info.value.code == "EXTERNAL_PROCESSING_NOT_CONSENTED"
    assert exc_info.value.status_code == 403


async def test_explain_line_requires_configured_key(monkeypatch):
    monkeypatch.setattr(
        explain,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"explanation_provider": "gemini", "gemini_api_key": "", "gemini_model": "x"},
        )(),
    )
    case = _case()
    line = _line()

    with pytest.raises(AppError) as exc_info:
        await explain.explain_line(case, line, None, "why?")
    assert exc_info.value.code == "AI_NOT_CONFIGURED"
    assert exc_info.value.status_code == 503


async def test_explain_line_rejects_overlong_question(monkeypatch):
    _patch_gemini(monkeypatch)
    case = _case()
    line = _line()

    with pytest.raises(AppError) as exc_info:
        await explain.explain_line(case, line, None, "x" * (explain.MAX_QUESTION_CHARS + 1))
    assert exc_info.value.code == "QUESTION_TOO_LONG"


async def test_explain_line_sends_only_already_computed_data(monkeypatch):
    """The DATA block must be built entirely from the line/comparison already
    on hand -- this is what stops the AI from inventing a number: it's never
    given anything to invent from."""
    capture = _patch_gemini(monkeypatch)
    case = _case()
    line = _line(billed_amount=Decimal("450.00"))

    result = await explain.explain_line(case, line, None, "why?")

    assert result.answer == "A plain-language explanation."
    assert result.model
    prompt = capture["contents"]
    assert "450.00" in prompt
    assert "No comparison has been run" in prompt
    assert "why?" in prompt
    assert capture["config"].system_instruction == explain._SYSTEM_INSTRUCTION


async def test_explain_line_raises_on_empty_ai_response(monkeypatch):
    _patch_gemini(monkeypatch, text=None)
    case = _case()
    line = _line()

    with pytest.raises(AppError) as exc_info:
        await explain.explain_line(case, line, None, "why?")
    assert exc_info.value.code == "AI_NO_RESPONSE"


async def test_ask_case_question_requires_a_question(monkeypatch):
    _patch_gemini(monkeypatch)
    case = _case()

    with pytest.raises(AppError) as exc_info:
        await explain.ask_case_question(case, [_line()], [], "   ")
    assert exc_info.value.code == "QUESTION_REQUIRED"


async def test_ask_case_question_includes_every_line(monkeypatch):
    capture = _patch_gemini(monkeypatch)
    case = _case()
    lines = [_line(id="a", code="71046"), _line(id="b", code="80053")]

    await explain.ask_case_question(case, lines, [], "what's going on?")

    prompt = capture["contents"]
    assert "Line 1:" in prompt
    assert "Line 2:" in prompt
    assert "71046" in prompt
    assert "80053" in prompt


async def test_deterministic_provider_works_without_api_key(monkeypatch):
    monkeypatch.setattr(
        explain,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {"explanation_provider": "deterministic", "gemini_api_key": "", "gemini_model": ""},
        )(),
    )
    case = _case()
    line = _line(code="71046")

    result = await explain.explain_line(case, line, None, "What does this mean?")

    assert result.model == "deterministic"
    assert "71046" in result.answer
    assert "not run a comparison" in result.answer
