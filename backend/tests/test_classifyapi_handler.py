import json
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from classifyapi import handler as h
from classifyapi.codes import new_code
from classifyapi.store import CodeStore
from integrations.bedrock import BedrockClient, ToolResult

SECRET_SUBJECT = "SECRET-SUBJECT-DO-NOT-LOG"
SECRET_BODY = "SECRET-BODY-DO-NOT-LOG and a deadline"


@pytest.fixture
def api(aws_credentials: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[CodeStore, str]]:
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="eu-north-1")
        ddb.create_table(
            TableName="JobTrackerCodes-test",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("CODES_TABLE", "JobTrackerCodes-test")
        monkeypatch.setenv("CLASSIFIER_MODEL_ID", "eu.anthropic.claude-haiku-4-5")

        # fake Bedrock so no real call is made
        class _FakeBedrock(BedrockClient):
            def __init__(self) -> None:  # no boto client
                pass

            def converse_tool(self, **kwargs: Any) -> ToolResult:
                return ToolResult(
                    tool_input={
                        "is_job_application_email": True,
                        "email_type": "confirmation",
                        "company": "Example Bank",
                        "confidence": 0.95,
                        "summary": "application received",
                    },
                    input_tokens=120,
                    output_tokens=25,
                    stop_reason="tool_use",
                )

        monkeypatch.setattr(h, "BedrockClient", _FakeBedrock)
        store = CodeStore(ddb.Table("JobTrackerCodes-test"))
        yield store, "JobTrackerCodes-test"


def _event(raw_code: str | None, emails: list[dict] | None, path: str = "/classify") -> dict:
    headers = {}
    if raw_code is not None:
        headers["authorization"] = f"Bearer {raw_code}"
    return {
        "rawPath": path,
        "headers": headers,
        "requestContext": {"http": {"method": "GET" if path == "/health" else "POST"}},
        "body": json.dumps({"timezone": "Europe/London", "emails": emails or []}),
    }


def _email() -> dict:
    return {
        "sender": "careers@bank.com",
        "subject": SECRET_SUBJECT,
        "body_text": SECRET_BODY,
        "received": "2026-10-06T09:00:00+00:00",
        "folder": "inbox",
    }


def test_health() -> None:
    event = {"rawPath": "/health", "headers": {}, "requestContext": {"http": {"method": "GET"}}}
    resp = h.handler(event)
    assert resp["statusCode"] == 200


def test_missing_code_401(api: tuple[CodeStore, str]) -> None:
    resp = h.handler(_event(None, [_email()]))
    assert resp["statusCode"] == 401


def test_invalid_code_403(api: tuple[CodeStore, str]) -> None:
    resp = h.handler(_event("jt_deadbeef_nope", [_email()]))
    assert resp["statusCode"] == 403


def test_revoked_code_403(api: tuple[CodeStore, str]) -> None:
    store, _ = api
    code, raw = new_code("Sam")
    store.put_code(code)
    store.revoke_code(code.code_id)
    resp = h.handler(_event(raw, [_email()]))
    assert resp["statusCode"] == 403


def test_classify_happy_path(api: tuple[CodeStore, str]) -> None:
    store, _ = api
    code, raw = new_code("Sam")
    store.put_code(code)
    resp = h.handler(_event(raw, [_email()]))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["results"][0]["facts"]["company"] == "Example Bank"
    assert body["usage"]["classified"] == 1
    assert body["usage"]["tokens_in"] == 120
    # usage persisted against the code
    assert store.get_usage(code.code_id).requests == 1


def test_cap_marks_remaining_capped(api: tuple[CodeStore, str]) -> None:
    store, _ = api
    code, raw = new_code("Sam", daily_request_cap=1)
    store.put_code(code)
    resp = h.handler(_event(raw, [_email(), _email()]))
    body = json.loads(resp["body"])
    assert body["usage"]["classified"] == 1
    assert body["usage"]["capped"] == 1
    assert body["results"][1] == {"capped": True}


def test_no_email_content_in_logs(
    api: tuple[CodeStore, str], caplog: pytest.LogCaptureFixture
) -> None:
    store, _ = api
    code, raw = new_code("Sam")
    store.put_code(code)
    import logging

    with caplog.at_level(logging.INFO):
        h.handler(_event(raw, [_email()]))
    blob = json.dumps([r.__dict__ for r in caplog.records], default=str)
    assert SECRET_SUBJECT not in blob
    assert SECRET_BODY not in blob
    assert "careers@bank.com" not in blob


def test_empty_emails_400(api: tuple[CodeStore, str]) -> None:
    store, _ = api
    code, raw = new_code("Sam")
    store.put_code(code)
    resp = h.handler(_event(raw, []))
    assert resp["statusCode"] == 400


def _me_event(raw_code: str | None) -> dict:
    headers = {}
    if raw_code is not None:
        headers["authorization"] = f"Bearer {raw_code}"
    return {"rawPath": "/me", "headers": headers, "requestContext": {"http": {"method": "GET"}}}


def test_me_returns_tab(api: tuple[CodeStore, str]) -> None:
    store, _ = api
    code, raw = new_code("Sam")
    store.put_code(code)
    # classify two emails to build usage
    h.handler(_event(raw, [_email(), _email()]))
    resp = h.handler(_me_event(raw))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["username"] == "sam"
    assert body["emails_classified"] == 2
    assert body["tab_gbp"] >= 0.0
    assert "tab_pints" in body


def test_me_requires_auth(api: tuple[CodeStore, str]) -> None:
    assert h.handler(_me_event(None))["statusCode"] == 401
    assert h.handler(_me_event("jt_nope_x"))["statusCode"] == 403


# --- prospects: rank -----------------------------------------------------
SECRET_COMPANY = "SECRET-COMPANY-DO-NOT-LOG"


def _rank_event(raw_code: str | None, results: list[dict] | None) -> dict:
    headers = {}
    if raw_code is not None:
        headers["authorization"] = f"Bearer {raw_code}"
    return {
        "rawPath": "/prospects/rank",
        "headers": headers,
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps(
            {"profile": {"programme": "Graduate", "start_year": 2027}, "results": results or []}
        ),
    }


def _rank_bedrock() -> type[BedrockClient]:
    class _FakeRankBedrock(BedrockClient):
        def __init__(self) -> None:
            pass

        def converse_tool(self, **kwargs: Any) -> ToolResult:
            return ToolResult(
                tool_input={
                    "is_job": True,
                    "company": SECRET_COMPANY,
                    "role": "Quant Trader",
                    "programme": "Graduate",
                    "location": "London",
                    "fit": 5,
                    "why": "strong match",
                },
                input_tokens=200,
                output_tokens=30,
                stop_reason="tool_use",
            )

    return _FakeRankBedrock


def test_rank_happy_path(
    api: tuple[CodeStore, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = api
    monkeypatch.setattr(h, "BedrockClient", _rank_bedrock())
    code, raw = new_code("Sam")
    store.put_code(code)
    results = [{"title": "a", "url": "https://jobs.example.com/1", "snippet": "s"}]
    resp = h.handler(_rank_event(raw, results))
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["prospects"]) == 1
    assert body["prospects"][0]["url"] == "https://jobs.example.com/1"
    assert body["prospects"][0]["fit"] == 5
    assert body["tokens_in"] == 200
    # tokens billed to the tab
    assert store.get_usage(code.code_id).input_tokens == 200


def test_rank_requires_profile(api: tuple[CodeStore, str]) -> None:
    store, _ = api
    code, raw = new_code("Sam")
    store.put_code(code)
    event = _rank_event(raw, [{"url": "https://x.com/1"}])
    event["body"] = json.dumps({"results": [{"url": "https://x.com/1"}]})
    assert h.handler(event)["statusCode"] == 400


def test_rank_rejects_oversized_batch(api: tuple[CodeStore, str]) -> None:
    store, _ = api
    code, raw = new_code("Sam")
    store.put_code(code)
    results = [{"url": f"https://x.com/{i}"} for i in range(11)]
    assert h.handler(_rank_event(raw, results))["statusCode"] == 400


def test_rank_requires_auth(api: tuple[CodeStore, str]) -> None:
    assert h.handler(_rank_event(None, [{"url": "https://x.com/1"}]))["statusCode"] == 401


def test_rank_no_content_in_logs(
    api: tuple[CodeStore, str], monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store, _ = api
    monkeypatch.setattr(h, "BedrockClient", _rank_bedrock())
    code, raw = new_code("Sam")
    store.put_code(code)
    import logging

    with caplog.at_level(logging.INFO):
        h.handler(_rank_event(raw, [{"url": "https://jobs.example.com/1", "title": "t"}]))
    blob = json.dumps([r.__dict__ for r in caplog.records], default=str)
    assert SECRET_COMPANY not in blob
    assert "jobs.example.com" not in blob
