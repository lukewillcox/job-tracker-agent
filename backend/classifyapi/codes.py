"""Invite-code generation and verification.

A code looks like ``jt_<code_id>_<secret>``. Only the sha256 of the whole code
is stored; the raw code is shown once at creation. ``code_id`` is the public
handle used in admin listings and usage reports.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets

from classifyapi.models import InviteCode

_PREFIX = "jt"


def hash_code(raw_code: str) -> str:
    return hashlib.sha256(raw_code.encode("utf-8")).hexdigest()


def new_code(
    label: str,
    daily_request_cap: int = 300,
    daily_token_cap: int = 2_000_000,
) -> tuple[InviteCode, str]:
    """Create a new invite code. Returns (stored record, raw code to hand out)."""

    code_id = secrets.token_hex(4)  # 8 hex chars, public handle
    secret = secrets.token_urlsafe(24)  # the private part
    raw = f"{_PREFIX}_{code_id}_{secret}"
    code = InviteCode(
        code_id=code_id,
        code_hash=hash_code(raw),
        label=label,
        created_at=dt.datetime.now(dt.UTC),
        daily_request_cap=daily_request_cap,
        daily_token_cap=daily_token_cap,
    )
    return code, raw


def parse_code_id(raw_code: str) -> str | None:
    """Extract the public code_id from a raw code, or None if malformed.

    The secret part may itself contain ``_`` (base64url), so split into at most
    three parts and keep the remainder as the secret.
    """

    parts = raw_code.split("_", 2)
    if len(parts) != 3 or parts[0] != _PREFIX or not parts[1]:
        return None
    return parts[1]


def verify(raw_code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_code(raw_code), stored_hash)
