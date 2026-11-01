"""Classify one email into :class:`EmailFacts` with Bedrock tool use.

On a schema-validation failure it retries once (feeding the error back), then
falls back to a low-confidence ``other`` result so the matcher marks the
application ``Check email`` (Requirement 3.5/3.6). Relative deadlines are
resolved in code from the email's received time and the user's time zone.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from pydantic import ValidationError

from agent.classify.deadline import resolve_relative_deadline
from agent.prompts import load_prompt
from domain.enums import DeadlineKind, EmailType
from domain.models import EmailFacts
from integrations.bedrock import BedrockClient

PROMPT_VERSION = "classify_v1"
CONFIDENCE_THRESHOLD = 0.6
_TOOL_NAME = "record_email_facts"
_TOOL_DESCRIPTION = "Record the structured facts extracted from one email."


@dataclass
class ClassifyInput:
    sender: str
    subject: str
    body_text: str
    received: dt.datetime
    timezone: str = "Europe/London"
    folder: str = "inbox"


@dataclass
class ClassifyResult:
    facts: EmailFacts
    input_tokens: int
    output_tokens: int
    prompt_version: str
    fell_back: bool


def _tool_schema() -> dict[str, object]:
    schema = EmailFacts.model_json_schema()
    # Bedrock tool input schema is plain JSON Schema; drop pydantic's $defs refs
    # by inlining is unnecessary here since enums are embedded, but we strip the
    # title for a cleaner spec.
    schema.pop("title", None)
    return schema


def classify_email(
    client: BedrockClient,
    model_id: str,
    data: ClassifyInput,
) -> ClassifyResult:
    system = load_prompt(PROMPT_VERSION)
    user_text = _build_user_text(data)
    schema = _tool_schema()

    in_tok = out_tok = 0
    last_error: str | None = None

    for _attempt in range(2):  # one retry (Requirement 3.6)
        if last_error is None:
            prompt = user_text
        else:
            prompt = (
                f"{user_text}\n\nPrevious output was invalid: {last_error}\n"
                "Return valid fields."
            )
        result = client.converse_tool(
            model_id=model_id,
            system=system,
            user_text=prompt,
            tool_name=_TOOL_NAME,
            tool_description=_TOOL_DESCRIPTION,
            tool_schema=schema,
        )
        in_tok += result.input_tokens
        out_tok += result.output_tokens
        if result.tool_input is None:
            last_error = "no tool call returned"
            continue
        try:
            facts = EmailFacts.model_validate(result.tool_input)
        except ValidationError as exc:
            last_error = str(exc)[:500]
            continue

        facts = _post_process(facts, data)
        return ClassifyResult(facts, in_tok, out_tok, PROMPT_VERSION, fell_back=False)

    # both attempts failed schema validation -> Check email fallback
    return ClassifyResult(
        _fallback_facts(), in_tok, out_tok, PROMPT_VERSION, fell_back=True
    )


def _post_process(facts: EmailFacts, data: ClassifyInput) -> EmailFacts:
    # resolve a relative deadline the model left to us
    if facts.deadline is None and facts.deadline_text:
        resolved = resolve_relative_deadline(facts.deadline_text, data.received, data.timezone)
        if resolved is not None:
            facts = facts.model_copy(
                update={"deadline": resolved, "deadline_kind": DeadlineKind.ESTIMATED}
            )
    # low confidence -> force a Check email outcome downstream
    if facts.is_job_application_email and facts.confidence < CONFIDENCE_THRESHOLD:
        facts = facts.model_copy(update={"email_type": EmailType.OTHER})
    return facts


def _fallback_facts() -> EmailFacts:
    return EmailFacts(
        is_job_application_email=True,
        email_type=EmailType.OTHER,
        summary="Could not classify; check email",
        confidence=0.0,
    )


def _build_user_text(data: ClassifyInput) -> str:
    today = data.received.astimezone(dt.UTC).date().isoformat()
    return (
        f"Today's date: {today}. User time zone: {data.timezone}. "
        f"Folder: {data.folder}.\n"
        f"From: {data.sender}\n"
        f"Subject: {data.subject}\n"
        f"Received: {data.received.isoformat()}\n\n"
        f"Body:\n{data.body_text}"
    )
