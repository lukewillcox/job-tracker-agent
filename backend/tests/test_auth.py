from typing import Any

import pytest

from api import auth
from store.repository import Repository

SIGNING_KEY = "test-signing-key"


class _FakeMsal:
    """Stands in for msal.ConfidentialClientApplication."""

    def __init__(self, token_result: dict[str, Any] | None = None) -> None:
        self._token_result = token_result or {
            "id_token_claims": {
                "oid": "ms-user-123",
                "preferred_username": "luke.willcox@outlook.com",
                "name": "Luke Willcox",
                "tid": "personal",
            },
            "refresh_token": "RT-abc",
        }

    def initiate_auth_code_flow(self, scopes: list[str], redirect_uri: str) -> dict[str, Any]:
        return {
            "state": "state-xyz",
            "auth_uri": "https://login.microsoftonline.com/common/authorize?state=state-xyz",
            "code_verifier": "cv",
        }

    def acquire_token_by_auth_code_flow(
        self, flow: dict[str, Any], params: dict[str, Any]
    ) -> dict[str, Any]:
        return self._token_result


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TABLE_NAME", "JobTracker-test")
    monkeypatch.setenv("SESSION_SIGNING_KEY", SIGNING_KEY)
    monkeypatch.setenv("MS_REDIRECT_URI", "http://localhost:8000/api/auth/callback")
    monkeypatch.setenv("WEB_ORIGIN", "https://app.example.com")
    from store import client

    client.get_repository.cache_clear()


def _patch_msal(monkeypatch: pytest.MonkeyPatch, fake: _FakeMsal) -> list[tuple[str, str]]:
    monkeypatch.setattr(auth, "_build_msal_app", lambda: fake)
    stored: list[tuple[str, str]] = []
    monkeypatch.setattr(
        auth, "_encrypt_refresh_token", lambda uid, tok: f"enc({uid}:{tok})"
    )
    return stored


def test_login_redirects_and_stores_flow(
    monkeypatch: pytest.MonkeyPatch, table: object, repo: Repository
) -> None:
    _patch_msal(monkeypatch, _FakeMsal())
    resp = auth.login_handler({})
    assert resp["statusCode"] == 302
    assert "login.microsoftonline.com" in resp["headers"]["Location"]
    # the in-flight flow was persisted for the callback
    assert repo.take_auth_flow("state-xyz") is not None


def test_callback_happy_path_sets_cookie_and_user(
    monkeypatch: pytest.MonkeyPatch, table: object, repo: Repository
) -> None:
    _patch_msal(monkeypatch, _FakeMsal())
    auth.login_handler({})  # seed the flow
    resp = auth.callback_handler(
        {"queryStringParameters": {"state": "state-xyz", "code": "authcode"}}
    )
    assert resp["statusCode"] == 302
    assert resp["headers"]["Location"] == "https://app.example.com"
    assert "jt_session=" in resp["headers"]["Set-Cookie"]
    assert "HttpOnly" in resp["headers"]["Set-Cookie"]

    user = repo.get_user("ms-user-123")
    assert user is not None
    assert user.email == "luke.willcox@outlook.com"
    assert user.status.value == "active"
    # refresh token was encrypted and stored off the profile JSON
    assert repo.get_user_secret("ms-user-123") == "enc(ms-user-123:RT-abc)"


def test_callback_rejects_unknown_state(
    monkeypatch: pytest.MonkeyPatch, table: object, repo: Repository
) -> None:
    _patch_msal(monkeypatch, _FakeMsal())
    resp = _as_response(
        lambda: auth.callback_handler({"queryStringParameters": {"state": "nope"}})
    )
    assert resp == 400


def test_callback_declined_consent(
    monkeypatch: pytest.MonkeyPatch, table: object, repo: Repository
) -> None:
    fake = _FakeMsal({"error": "access_denied", "error_description": "user declined"})
    _patch_msal(monkeypatch, fake)
    auth.login_handler({})
    resp = _as_response(
        lambda: auth.callback_handler(
            {"queryStringParameters": {"state": "state-xyz", "code": "x"}}
        )
    )
    assert resp == 400


def test_logout_clears_cookie() -> None:
    resp = auth.logout_handler({})
    assert resp["statusCode"] == 204
    assert "Max-Age=0" in resp["headers"]["Set-Cookie"]


def _as_response(fn: Any) -> int:
    from api.responses import ApiError

    try:
        fn()
    except ApiError as exc:
        return exc.status
    return 200
