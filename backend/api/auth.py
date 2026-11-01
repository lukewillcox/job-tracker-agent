"""Microsoft sign-in handlers (Task 4).

Flow (design.md "Auth"):
  GET  /api/auth/login    -> build the Microsoft authorize URL (MSAL
                             initiate_auth_code_flow: PKCE + state + nonce),
                             stash the in-flight flow in DynamoDB (TTL 10 min),
                             redirect the browser to Microsoft.
  GET  /api/auth/callback -> exchange the code, validate the id token, upsert the
                             user, KMS-encrypt the refresh token (encryption
                             context = user_id), set the signed session cookie,
                             redirect to the app.
  POST /api/auth/logout   -> clear the session cookie.

The confidential-client secret is read from Secrets Manager at runtime; it is
never in code. MSAL and the secret lookup are injected via module functions so
the handlers are unit-testable offline.
"""

from __future__ import annotations

import os
import time
from typing import Any

from api.responses import ApiError
from api.session import cookie_header, issue_session
from domain.enums import UserStatus
from domain.models import User
from integrations.ms_config import load_config
from store.client import get_repository
from store.repository import Repository

_AUTH_FLOW_TTL = 600  # 10 minutes


# --- injectable dependencies (overridden in tests) ----------------------
def _build_msal_app() -> Any:
    """Construct the MSAL confidential client (real network/secret path)."""

    import msal

    from integrations.secrets import ms_client_secret

    cfg = load_config()
    return msal.ConfidentialClientApplication(
        client_id=cfg.client_id,
        authority=cfg.authority,
        client_credential=ms_client_secret(),
    )


def _signing_key() -> str:
    key = os.environ.get("SESSION_SIGNING_KEY")
    if key:
        return key
    from integrations.secrets import session_signing_key

    return session_signing_key()


def _encrypt_refresh_token(user_id: str, token: str) -> str:
    from integrations.token_crypto import encrypt_refresh_token

    return encrypt_refresh_token(user_id, token)


# --- handlers -----------------------------------------------------------
def login_handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    cfg = load_config()
    app = _build_msal_app()
    flow = app.initiate_auth_code_flow(
        scopes=list(cfg.scopes),
        redirect_uri=cfg.redirect_uri,
    )
    repo = get_repository()
    repo.put_auth_flow(flow["state"], flow, ttl=int(time.time()) + _AUTH_FLOW_TTL)
    return _redirect(flow["auth_uri"])


def callback_handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    params = event.get("queryStringParameters") or {}
    state = params.get("state")
    if not state:
        raise ApiError(400, "missing state")

    repo = get_repository()
    flow = repo.take_auth_flow(state)
    if flow is None:
        raise ApiError(400, "unknown or expired auth flow")

    app = _build_msal_app()
    result = app.acquire_token_by_auth_code_flow(flow, params)
    if "error" in result:
        # user declined consent or the exchange failed (Requirement 1.5)
        raise ApiError(400, result.get("error_description", result["error"]))

    user = _upsert_user(repo, result)
    token = issue_session(user.user_id, _signing_key())
    return _redirect(_web_origin(), extra_headers={"Set-Cookie": cookie_header(token)})


def logout_handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    expired = "jt_session=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0"
    return {"statusCode": 204, "headers": {"Set-Cookie": expired}, "body": ""}


# --- helpers ------------------------------------------------------------
def _upsert_user(repo: Repository, token_result: dict[str, Any]) -> User:
    claims = token_result.get("id_token_claims", {})
    user_id = claims.get("oid") or claims.get("sub")
    if not user_id:
        raise ApiError(400, "no subject in id token")
    email = claims.get("preferred_username") or claims.get("email") or ""
    name = claims.get("name")

    existing = repo.get_user(user_id)
    user = existing or User(user_id=user_id, email=email)
    user.email = email or user.email
    user.name = name or user.name
    user.status = UserStatus.ACTIVE
    user.scopes = list(load_config().scopes)
    user.ms_account_type = claims.get("tid")

    repo.put_user(user)

    refresh_token = token_result.get("refresh_token")
    if refresh_token:
        _store_refresh_token(repo, user, refresh_token)
    return user


def _store_refresh_token(repo: Repository, user: User, refresh_token: str) -> None:
    # Encrypt with KMS (user-bound encryption context) and persist on the user.
    encrypted = _encrypt_refresh_token(user.user_id, refresh_token)
    repo.put_user_secret(user.user_id, encrypted)


def _web_origin() -> str:
    return os.environ.get("WEB_ORIGIN", "/")


def _redirect(location: str, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
    headers = {"Location": location}
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": 302, "headers": headers, "body": ""}
