"""Session cookie signing and verification.

The design calls for a signed session JWT in an httpOnly cookie. To avoid an
extra dependency this uses a compact HMAC-SHA256 token with the same security
properties for our use (integrity + expiry): ``base64url(payload).base64url(sig)``
where ``payload`` is JSON ``{"uid": ..., "exp": epoch}``.

The signing key is the ``session_signing_key`` from the app secret. Nothing here
logs the key or the token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from api.responses import ApiError

_COOKIE_NAME = "jt_session"
_DEFAULT_TTL = 7 * 24 * 3600  # 7-day sliding expiry (design)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def issue_session(user_id: str, signing_key: str, ttl: int = _DEFAULT_TTL) -> str:
    payload = json.dumps({"uid": user_id, "exp": int(time.time()) + ttl}).encode()
    body = _b64url(payload)
    sig = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64url(sig)}"


def verify_session(token: str, signing_key: str, now: int | None = None) -> str:
    """Return the user id from a valid token, or raise :class:`ApiError` (401)."""

    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(signing_key.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig), expected):
            raise ApiError(401, "invalid session")
        payload = json.loads(_b64url_decode(body))
    except ApiError:
        raise
    except Exception as exc:  # malformed token
        raise ApiError(401, "invalid session") from exc

    if int(payload.get("exp", 0)) < (now if now is not None else int(time.time())):
        raise ApiError(401, "session expired")
    uid = payload.get("uid")
    if not isinstance(uid, str) or not uid:
        raise ApiError(401, "invalid session")
    return uid


def cookie_header(token: str, ttl: int = _DEFAULT_TTL) -> str:
    return (
        f"{_COOKIE_NAME}={token}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={ttl}"
    )


def read_cookie(headers: dict[str, str]) -> str | None:
    raw = headers.get("cookie") or headers.get("Cookie")
    if not raw:
        return None
    for part in raw.split(";"):
        name, _, value = part.strip().partition("=")
        if name == _COOKIE_NAME:
            return value
    return None
