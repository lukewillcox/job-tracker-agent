"""Release the per-user scan lock (Step Functions terminal step).

Runs both on the happy path (after notify) and from a Catch on failure, so a
scan that fails part-way doesn't leave the user locked until the TTL expires.
Idempotent: deleting an absent lock is a no-op.
"""

from __future__ import annotations

from typing import Any

from store.client import get_repository


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    user_id = _extract_user_id(event)
    if user_id:
        get_repository().release_scan_lock(user_id)
    return {"released": bool(user_id), "user_id": user_id}


def _extract_user_id(event: dict[str, Any]) -> str | None:
    # happy path: user_id is on the state; catch path: the error is wrapped, so
    # fall back to the original input the workflow was started with.
    uid = event.get("user_id")
    if isinstance(uid, str):
        return uid
    original = event.get("input") or {}
    if isinstance(original, dict):
        oid = original.get("user_id")
        return oid if isinstance(oid, str) else None
    return None
