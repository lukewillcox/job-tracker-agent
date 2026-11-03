"""Microsoft Graph client.

Responsibilities (Task 4):
  - exchange a stored refresh token for a fresh access token via MSAL
    (confidential client), and surface the rotated refresh token so the caller
    can re-encrypt and store it;
  - make Graph v1.0 requests, honouring ``Retry-After`` on 429/5xx (and retrying
    dropped connections) with bounded retries (tech.md: respect Retry-After).

Network dependencies (the MSAL app and the HTTP session) are injected so the
client is unit-testable without hitting Microsoft.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import requests

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_MAX_RETRIES = 4
_DEFAULT_TIMEOUT = 30
# throttling + transient server errors Graph returns now and then
_RETRY_STATUSES = (429, 500, 502, 503, 504)


class TokenAcquisitionError(RuntimeError):
    """Raised when a refresh token can't be exchanged (revoked/expired)."""


@dataclass
class TokenResult:
    access_token: str
    refresh_token: str | None  # rotated token, if Microsoft returned a new one


class MsalApp(Protocol):
    """The slice of msal.ConfidentialClientApplication we use."""

    def acquire_token_by_refresh_token(
        self, refresh_token: str, scopes: list[str]
    ) -> dict[str, Any]: ...


class GraphClient:
    def __init__(
        self,
        access_token: str,
        session: requests.Session | None = None,
        sleep: Any = time.sleep,
    ) -> None:
        self._token = access_token
        self._session = session or requests.Session()
        self._sleep = sleep

    # --- token exchange --------------------------------------------------
    @classmethod
    def from_refresh_token(
        cls,
        msal_app: MsalApp,
        refresh_token: str,
        scopes: list[str],
        session: requests.Session | None = None,
    ) -> tuple[GraphClient, TokenResult]:
        result = msal_app.acquire_token_by_refresh_token(refresh_token, scopes=scopes)
        if "access_token" not in result:
            raise TokenAcquisitionError(result.get("error_description", "token exchange failed"))
        token = TokenResult(
            access_token=result["access_token"],
            refresh_token=result.get("refresh_token"),
        )
        return cls(token.access_token, session=session), token

    # --- requests --------------------------------------------------------
    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path_or_url, params=params)

    def _request(
        self,
        method: str,
        path_or_url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = path_or_url if path_or_url.startswith("http") else f"{GRAPH_BASE}{path_or_url}"
        headers = {"Authorization": f"Bearer {self._token}"}

        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._session.request(
                    method, url, headers=headers, params=params, timeout=_DEFAULT_TIMEOUT
                )
            except (requests.ConnectionError, requests.Timeout):
                if attempt == _MAX_RETRIES - 1:
                    raise
                self._sleep(float(2**attempt))
                continue
            if resp.status_code in _RETRY_STATUSES:
                if attempt == _MAX_RETRIES - 1:
                    resp.raise_for_status()
                self._sleep(self._retry_after(resp, attempt))
                continue
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()
            return body
        raise RuntimeError("unreachable")  # pragma: no cover

    @staticmethod
    def _retry_after(resp: requests.Response, attempt: int) -> float:
        header = resp.headers.get("Retry-After")
        if header is not None:
            try:
                return float(header)
            except ValueError:
                pass
        # exponential backoff fallback when the header is absent/unparseable
        return float(2**attempt)
