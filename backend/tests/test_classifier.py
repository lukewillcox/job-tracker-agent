import datetime as dt
from typing import Any

from agent.classify.classifier import CONFIDENCE_THRESHOLD, ClassifyInput, classify_email
from domain.enums import EmailType
from integrations.bedrock import BedrockClient, ToolResult


class FakeBedrock(BedrockClient):
    """A BedrockClient returning scripted tool inputs without boto3."""

    def __init__(self, tool_inputs: list[dict[str, Any] | None]) -> None:
        self._inputs = tool_inputs
        self.calls: list[dict[str, Any]] = []

    def converse_tool(self, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        self.calls.append(kwargs)
        value = self._inputs.pop(0)
        return ToolResult(
            tool_input=value, input_tokens=100, output_tokens=20, stop_reason="tool_use"
        )


RECEIVED = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def _input(**kw: Any) -> ClassifyInput:
    base = {
        "sender": "careers@bank.com",
        "subject": "Your application",
        "body_text": "Thank you for applying.",
        "received": RECEIVED,
    }
    base.update(kw)
    return ClassifyInput(**base)  # type: ignore[arg-type]


def _facts(**kw: Any) -> dict[str, Any]:
    base = {
        "is_job_application_email": True,
        "email_type": "confirmation",
        "company": "Example Bank",
        "confidence": 0.95,
        "summary": "application received",
    }
    base.update(kw)
    return base


def test_valid_classification() -> None:
    client = FakeBedrock([_facts()])
    result = classify_email(client, "model-x", _input())
    assert result.facts.email_type == EmailType.CONFIRMATION
    assert result.facts.company == "Example Bank"
    assert result.fell_back is False
    assert result.input_tokens == 100


def test_retry_once_then_succeeds() -> None:
    # first call returns an invalid enum, second is valid
    client = FakeBedrock([_facts(email_type="not_a_real_type"), _facts()])
    result = classify_email(client, "model-x", _input())
    assert result.fell_back is False
    assert len(client.calls) == 2
    assert result.input_tokens == 200  # both calls counted


def test_falls_back_to_check_email_after_two_failures() -> None:
    client = FakeBedrock([{"garbage": True}, {"garbage": True}])
    result = classify_email(client, "model-x", _input())
    assert result.fell_back is True
    assert result.facts.email_type == EmailType.OTHER
    assert result.facts.confidence == 0.0


def test_low_confidence_forced_to_other() -> None:
    client = FakeBedrock([_facts(confidence=CONFIDENCE_THRESHOLD - 0.1)])
    result = classify_email(client, "model-x", _input())
    assert result.facts.email_type == EmailType.OTHER  # -> Check email downstream


def test_relative_deadline_resolved() -> None:
    client = FakeBedrock(
        [
            _facts(
                email_type="assessment_invite",
                deadline=None,
                deadline_text="within 5 days",
                confidence=0.9,
            )
        ]
    )
    result = classify_email(client, "model-x", _input())
    assert result.facts.deadline is not None
    assert result.facts.deadline.date() == dt.date(2026, 10, 11)


def test_no_tool_call_then_fallback() -> None:
    client = FakeBedrock([None, None])
    result = classify_email(client, "model-x", _input())
    assert result.fell_back is True
