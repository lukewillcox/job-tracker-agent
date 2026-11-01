"""Helpers for building HTTP API (API Gateway v2 payload v2.0) responses."""

from __future__ import annotations

import json
from typing import Any

JSON_HEADERS = {"content-type": "application/json"}


def json_response(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": JSON_HEADERS,
        "body": json.dumps(body, default=str),
    }


def ok(body: Any) -> dict[str, Any]:
    return json_response(200, body)


def created(body: Any) -> dict[str, Any]:
    return json_response(201, body)


def no_content() -> dict[str, Any]:
    return {"statusCode": 204, "headers": {}, "body": ""}


def error(status: int, message: str) -> dict[str, Any]:
    return json_response(status, {"error": message})


class ApiError(Exception):
    """Raised by handlers to return a specific HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
