"""Shared classifier HTTPS API Lambda (API Gateway proxy).

POST /classify
  Authorization: Bearer <raw invite code>
  body: {"timezone": "...", "emails": [{"sender","subject","body_text",
         "received","folder"}], ...}
  -> {"results": [EmailFacts-or-null...], "usage": {...}}

Auth: the invite code is looked up by its public id and verified against the
stored hash. Each email classified charges one request against the code's daily
caps (atomic); when a cap trips, remaining emails return a "capped" marker.

Privacy: email content is used only for the transient Bedrock call. It is never
stored and never logged — logs carry only the code id, counts and token totals.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

from aws_lambda_powertools import Logger

from agent.classify.classifier import ClassifyInput, classify_email
from classifyapi.codes import parse_code_id, verify
from classifyapi.store import CapExceededError, CodeStore
from integrations.bedrock import BedrockClient

logger = Logger(service="job-tracker-classify-api")

# Bounded so a request completes inside the API Gateway HTTP API 30s integration
# timeout (~1-1.5s of Bedrock per email).
MAX_EMAILS_PER_REQUEST = 10


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    try:
        return _route(event)
    except _ApiError as exc:
        return _json(exc.status, {"error": exc.message})


class _ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _route(event: dict[str, Any]) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "POST")
    path = event.get("rawPath", "").rstrip("/")
    if path == "/health" and method == "GET":
        return _json(200, {"ok": True})

    store = _store()
    if path == "/me" and method == "GET":
        return _me(store, _authenticate(event, store))
    if path == "/classify" and method == "POST":
        code = _authenticate(event, store)
        return _classify_batch(store, code, _parse_body(event))
    raise _ApiError(404, "not found")


def _me(store: CodeStore, code: Any) -> dict[str, Any]:
    """Authenticated usage summary for the caller's own code (the beer tab)."""

    from classifyapi.billing import beers, cost_gbp

    usage = store.list_usage(code.code_id)
    emails = sum(u.requests for u in usage)
    tin = sum(u.input_tokens for u in usage)
    tout = sum(u.output_tokens for u in usage)
    gbp = cost_gbp(tin, tout)
    return _json(
        200,
        {
            "username": code.code_id,
            "emails_classified": emails,
            "tab_gbp": gbp,
            "tab_pints": beers(gbp),
        },
    )


# --- auth ----------------------------------------------------------------
def _authenticate(event: dict[str, Any], store: CodeStore) -> Any:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth = headers.get("authorization", "")
    raw = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not raw:
        raise _ApiError(401, "missing invite code")
    code_id = parse_code_id(raw)
    if not code_id:
        raise _ApiError(401, "malformed invite code")
    code = store.get_code(code_id)
    if code is None or not code.active or not verify(raw, code.code_hash):
        raise _ApiError(403, "invalid or revoked invite code")
    return code


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    try:
        body: dict[str, Any] = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        raise _ApiError(400, "invalid JSON body") from exc
    emails = body.get("emails")
    if not isinstance(emails, list) or not emails:
        raise _ApiError(400, "no emails provided")
    if len(emails) > MAX_EMAILS_PER_REQUEST:
        raise _ApiError(400, f"too many emails (max {MAX_EMAILS_PER_REQUEST})")
    return body


# --- classify ------------------------------------------------------------
def _classify_batch(store: CodeStore, code: Any, body: dict[str, Any]) -> dict[str, Any]:
    model_id = os.environ["CLASSIFIER_MODEL_ID"]
    timezone = body.get("timezone", "Europe/London")
    bedrock = BedrockClient()

    results: list[dict[str, Any]] = []
    classified = tokens_in = tokens_out = capped = 0

    for email in body["emails"]:
        try:
            store.charge_request(code)
        except CapExceededError:
            capped += 1
            results.append({"capped": True})
            continue

        received = dt.datetime.fromisoformat(str(email["received"]))
        result = classify_email(
            bedrock,
            model_id,
            ClassifyInput(
                sender=str(email.get("sender", "")),
                subject=str(email.get("subject", "")),
                body_text=str(email.get("body_text", "")),
                received=received,
                timezone=timezone,
                folder=str(email.get("folder", "inbox")),
            ),
        )
        store.record_tokens(code.code_id, result.input_tokens, result.output_tokens)
        classified += 1
        tokens_in += result.input_tokens
        tokens_out += result.output_tokens
        results.append({"facts": result.facts.model_dump(mode="json")})

    _maybe_alert_50pct(store, code)

    # counts only — NEVER log sender/subject/body (privacy guarantee)
    logger.info(
        "classify batch",
        extra={
            "code_id": code.code_id,
            "classified": classified,
            "capped": capped,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        },
    )
    return _json(
        200,
        {
            "results": results,
            "usage": {
                "classified": classified,
                "capped": capped,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            },
        },
    )


# --- 50% alert -----------------------------------------------------------
def _maybe_alert_50pct(store: CodeStore, code: Any) -> None:
    """Email the host once when a code passes 50% of its daily token backstop.

    Best-effort: never fails the request, never includes email content.
    """

    usage = store.get_usage(code.code_id)
    if usage.total_tokens < code.daily_token_cap * 0.5:
        return
    if not store.try_claim_50pct_alert(code.code_id):
        return  # already alerted today
    admin_email = os.environ.get("ADMIN_ALERT_EMAIL")
    ses_from = os.environ.get("SES_FROM")
    if not admin_email or not ses_from:
        return
    try:
        import boto3

        pct = int(usage.total_tokens / code.daily_token_cap * 100)
        boto3.client("sesv2").send_email(
            FromEmailAddress=ses_from,
            Destination={"ToAddresses": [admin_email]},
            Content={
                "Simple": {
                    "Subject": {"Data": f"Job Tracker: {code.code_id} at {pct}% of daily cap"},
                    "Body": {
                        "Text": {
                            "Data": (
                                f"{code.label} ({code.code_id}) has used {usage.total_tokens:,} "
                                f"tokens today, over 50% of the {code.daily_token_cap:,} backstop. "
                                "No action needed unless this looks runaway."
                            )
                        }
                    },
                }
            },
        )
    except Exception as exc:  # SES not configured / sandbox / transient
        logger.warning("50%% alert email not sent", extra={"reason": str(exc)[:160]})


# --- helpers -------------------------------------------------------------
def _store() -> CodeStore:
    import boto3

    table = boto3.resource("dynamodb").Table(os.environ["CODES_TABLE"])
    return CodeStore(table)


def _json(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=str),
    }
