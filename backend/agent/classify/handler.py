"""Classify Lambda (Step Functions Map step): one Bedrock call per message.

Receives a claim-check reference (the S3 key of one ingested message), reads the
message JSON from the scratch bucket, classifies it into :class:`EmailFacts`
with :func:`agent.classify.classifier.classify_email`, and returns the facts
plus the identifiers the match step needs. Token counts are returned for the
scan's cost accounting.

The Map passes each item as ``{"key": ..., "user_id": ..., "scan_id": ...}``.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

import boto3
from aws_lambda_powertools import Logger

from agent.classify.classifier import ClassifyInput, ClassifyResult, classify_email
from domain.enums import EmailType
from domain.models import EmailFacts
from integrations.bedrock import BedrockClient

_logger = Logger(service="job-tracker-classify")


def _check_email_result() -> ClassifyResult:
    facts = EmailFacts(
        is_job_application_email=True,
        email_type=EmailType.OTHER,
        summary="Classifier unavailable; check email",
        confidence=0.0,
    )
    return ClassifyResult(facts, 0, 0, prompt_version="classify_v1", fell_back=True)


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    model_id = os.environ["CLASSIFIER_MODEL_ID"]
    bucket = os.environ["SCRATCH_BUCKET"]

    msg = _read_message(bucket, event["key"])
    timezone = event.get("timezone", "Europe/London")
    received = dt.datetime.fromisoformat(msg["received"])

    try:
        result = classify_email(
            BedrockClient(),
            model_id,
            ClassifyInput(
                sender=msg["sender"],
                subject=msg["subject"],
                body_text=msg["body_text"],
                received=received,
                timezone=timezone,
                folder=msg.get("folder", "inbox"),
            ),
        )
    except Exception as exc:  # throttling after retries, transient Bedrock error
        # Don't fail the whole scan for one message: mark it Check email and
        # move on. It will be re-examined on the next scan.
        _logger.warning("classify failed; marking Check email", extra={"reason": str(exc)[:200]})
        result = _check_email_result()

    # return only facts + identifiers (no body) — small enough for the state
    return {
        "facts": result.facts.model_dump(mode="json"),
        "email_date": msg["received"],
        "message_id": msg["message_id"],
        "internet_message_id": msg["internet_message_id"],
        "conversation_id": msg.get("conversation_id"),
        "web_link": msg.get("web_link"),
        "prompt_version": result.prompt_version,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def _read_message(bucket: str, key: str) -> dict[str, Any]:
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=bucket, Key=key)
    data: dict[str, Any] = json.loads(obj["Body"].read())
    return data
