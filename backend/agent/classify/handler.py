"""Classify Lambda (Step Functions Map step): one Bedrock call per message.

Receives one ingested message, classifies it into :class:`EmailFacts` with the
implemented :func:`agent.classify.classifier.classify_email`, and returns the
facts plus the identifiers the match step needs. Token counts are returned for
the scan's cost accounting.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Any

from agent.classify.classifier import ClassifyInput, classify_email
from integrations.bedrock import BedrockClient


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    model_id = os.environ["CLASSIFIER_MODEL_ID"]
    timezone = event.get("timezone", "Europe/London")
    received = dt.datetime.fromisoformat(event["received"])

    result = classify_email(
        BedrockClient(),
        model_id,
        ClassifyInput(
            sender=event["sender"],
            subject=event["subject"],
            body_text=event["body_text"],
            received=received,
            timezone=timezone,
            folder=event.get("folder", "inbox"),
        ),
    )

    return {
        "facts": result.facts.model_dump(mode="json"),
        "email_date": event["received"],
        "message_id": event["message_id"],
        "internet_message_id": event["internet_message_id"],
        "conversation_id": event.get("conversation_id"),
        "web_link": event.get("web_link"),
        "prompt_version": result.prompt_version,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }
