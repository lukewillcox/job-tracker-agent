from typing import Any

import pytest
import requests

from integrations.graph_client import GraphClient, TokenAcquisitionError


class _FakeMsal:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.calls: list[tuple[str, list[str]]] = []

    def acquire_token_by_refresh_token(
        self, refresh_token: str, scopes: list[str]
    ) -> dict[str, Any]:
        self.calls.append((refresh_token, scopes))
        return self._result


class _FakeResponse:
    def __init__(self, status: int, body: dict | None = None, retry_after: str | None = None):
        self.status_code = status
        self._body = body or {}
        self.headers = {"Retry-After": retry_after} if retry_after else {}

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.requests: list[dict] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        return self._responses.pop(0)


def test_from_refresh_token_returns_rotated_token() -> None:
    msal = _FakeMsal({"access_token": "AT", "refresh_token": "NEW_RT"})
    _client, token = GraphClient.from_refresh_token(msal, "OLD_RT", ["Mail.Read"])
    assert token.access_token == "AT"
    assert token.refresh_token == "NEW_RT"
    assert msal.calls == [("OLD_RT", ["Mail.Read"])]


def test_from_refresh_token_raises_on_revoked() -> None:
    msal = _FakeMsal({"error": "invalid_grant", "error_description": "revoked"})
    with pytest.raises(TokenAcquisitionError, match="revoked"):
        GraphClient.from_refresh_token(msal, "OLD_RT", ["Mail.Read"])


def test_get_success() -> None:
    session = _FakeSession([_FakeResponse(200, {"value": [1, 2]})])
    client = GraphClient("AT", session=session)  # type: ignore[arg-type]
    body = client.get("/me/messages")
    assert body == {"value": [1, 2]}
    assert session.requests[0]["url"].endswith("/me/messages")
    assert session.requests[0]["headers"]["Authorization"] == "Bearer AT"


def test_retry_after_on_429_then_success() -> None:
    session = _FakeSession(
        [_FakeResponse(429, retry_after="2"), _FakeResponse(200, {"ok": True})]
    )
    slept: list[float] = []
    client = GraphClient("AT", session=session, sleep=slept.append)  # type: ignore[arg-type]
    body = client.get("/me")
    assert body == {"ok": True}
    assert slept == [2.0]  # honoured Retry-After


def test_retry_exhausted_raises() -> None:
    session = _FakeSession([_FakeResponse(503) for _ in range(4)])
    client = GraphClient("AT", session=session, sleep=lambda _s: None)  # type: ignore[arg-type]
    with pytest.raises(requests.HTTPError):
        client.get("/me")


def test_retries_transient_502_then_success() -> None:
    session = _FakeSession([_FakeResponse(502), _FakeResponse(200, {"ok": True})])
    client = GraphClient("tok", session=session, sleep=lambda s: None)  # type: ignore[arg-type]
    assert client.get("/me/messages/x") == {"ok": True}
    assert len(session.requests) == 2
