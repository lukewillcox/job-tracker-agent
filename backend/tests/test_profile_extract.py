"""POST /profile/extract: draft a search profile from CV text."""

import datetime as dt
import json
import logging
from typing import Any

import pytest

from classifyapi import handler as h
from classifyapi.codes import new_code
from classifyapi.cv import sanitise_draft
from classifyapi.store import CodeStore
from integrations.bedrock import BedrockClient, ToolResult
from tests.test_classifyapi_handler import api  # noqa: F401  (shared moto fixture)

SECRET_CV = "SECRET-CV-LINE-DO-NOT-LOG " + "MSc Physics at UCL, Python and C++. " * 20



def _event(raw_code: str | None, cv_text: Any) -> dict:
    headers = {"authorization": f"Bearer {raw_code}"} if raw_code else {}
    return {
        "rawPath": "/profile/extract",
        "headers": headers,
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps({"cv_text": cv_text}),
    }


class _FakeCvBedrock(BedrockClient):
    def __init__(self) -> None:
        pass

    def converse_tool(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            tool_input={
                "programme": "Graduate",
                "start_year": 2027,
                "degrees": ["MSc Physics (UCL)"],
                "skills": ["Python", "C++", "python"],
                "target_roles": ["quantitative analyst"],
                "locations": ["London"],
            },
            input_tokens=900,
            output_tokens=80,
            stop_reason="tool_use",
        )


@pytest.fixture
def cv_api(
    api: tuple[CodeStore, str],  # noqa: F811 (fixture imported above)
    monkeypatch: pytest.MonkeyPatch,
) -> CodeStore:
    monkeypatch.setattr(h, "BedrockClient", _FakeCvBedrock)
    return api[0]


def test_extract_happy_path_bills_tab(cv_api: CodeStore) -> None:
    code, raw = new_code("Sam")
    cv_api.put_code(code)
    resp = h.handler(_event(raw, SECRET_CV))
    assert resp["statusCode"] == 200
    prof = json.loads(resp["body"])["profile"]
    assert prof["degrees"] == ["MSc Physics (UCL)"]
    assert prof["skills"] == ["Python", "C++"]  # deduped case-insensitively
    assert cv_api.get_usage(code.code_id).input_tokens == 900


def test_extract_needs_auth_and_text(cv_api: CodeStore) -> None:
    assert h.handler(_event(None, SECRET_CV))["statusCode"] == 401
    code, raw = new_code("Sam")
    cv_api.put_code(code)
    assert h.handler(_event(raw, "too short"))["statusCode"] == 400
    assert h.handler(_event(raw, None))["statusCode"] == 400


def test_extract_never_logs_cv(cv_api: CodeStore, caplog: pytest.LogCaptureFixture) -> None:
    code, raw = new_code("Sam")
    cv_api.put_code(code)
    with caplog.at_level(logging.INFO):
        h.handler(_event(raw, SECRET_CV))
    blob = json.dumps([r.__dict__ for r in caplog.records], default=str)
    assert "SECRET-CV-LINE" not in blob
    assert "MSc Physics" not in blob


def test_sanitise_draft_coerces_bad_output() -> None:
    today = dt.date(2026, 11, 3)
    d = sanitise_draft({"programme": "grad", "start_year": 1999, "skills": "Python"}, today)
    assert d["programme"] == "Both"
    assert d["start_year"] == 2027
    assert d["skills"] == [] and d["degrees"] == [] and d["target_roles"] == []
    assert sanitise_draft(None, today)["start_year"] == 2027
