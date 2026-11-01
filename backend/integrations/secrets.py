"""Read the app secret (Microsoft client secret + session signing key)."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

import boto3


@lru_cache(maxsize=1)
def _app_secret() -> dict[str, Any]:
    arn = os.environ["APP_SECRETS_ARN"]
    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=arn)
    value: dict[str, Any] = json.loads(resp["SecretString"])
    return value


def session_signing_key() -> str:
    return str(_app_secret()["session_signing_key"])


def ms_client_secret() -> str:
    return str(_app_secret()["ms_client_secret"])


def clear_cache() -> None:
    """Testing hook to reset the cached secret."""

    _app_secret.cache_clear()
