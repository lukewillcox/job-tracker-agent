"""Brave Search API client (server-side only).

The API key is held in Secrets Manager and read at runtime; it is never in the
CLI or the repo (Requirement 2.3). Results are requested with a past-month
freshness filter where supported (Requirement 2.4). The ``requests`` session is
injectable so the client is unit-testable without network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import requests

_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_TIMEOUT = 10


@dataclass
class SearchResult:
    title: str
    snippet: str
    url: str
    age: str | None
    query: str


@lru_cache(maxsize=1)
def _api_key() -> str:
    """Read the Brave API key from Secrets Manager (cached per container)."""

    import boto3

    arn = os.environ["BRAVE_SECRET_ARN"]
    resp = boto3.client("secretsmanager").get_secret_value(SecretId=arn)
    secret = resp["SecretString"]
    # allow either a bare key or a JSON {"brave_api_key": "..."}
    if secret.lstrip().startswith("{"):
        import json

        return str(json.loads(secret).get("brave_api_key", "")).strip()
    return secret.strip()


class BraveClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None) -> None:
        self._key = api_key or _api_key()
        self._session = session or requests.Session()

    def search(self, query: str, count: int = 10, freshness: str = "pm") -> list[SearchResult]:
        """Run one query. ``freshness='pm'`` = past month. Returns [] on error."""

        params: dict[str, str | int] = {
            "q": query,
            "count": count,
            "freshness": freshness,
        }
        resp = self._session.get(
            _ENDPOINT,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self._key,
            },
            params=params,
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        return _parse(resp.json(), query)


def _parse(body: dict[str, Any], query: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    for item in body.get("web", {}).get("results", []):
        url = item.get("url")
        if not url:
            continue
        results.append(
            SearchResult(
                title=str(item.get("title", "")),
                snippet=str(item.get("description", "")),
                url=str(url),
                age=item.get("age"),
                query=query,
            )
        )
    return results
