"""HTTP API Lambda handler (design.md "API").

A single handler serves every ``/api/*`` route. It verifies the session cookie,
enforces tenant isolation (the ``user_id`` from the session is the only
partition a request can touch), and dispatches to small per-resource functions.

Auth sign-in/callback (``/api/auth/*``) is handled in ``api.auth`` and is not
wired here yet because it needs the live Microsoft identity platform; those
routes currently return 501.
"""

from __future__ import annotations

import os
from typing import Any

from api import analytics
from api.responses import ApiError, created, error, no_content, ok
from api.session import read_cookie, verify_session
from store.client import get_repository
from store.repository import Repository


def _signing_key() -> str:
    # Injected directly in tests via SESSION_SIGNING_KEY; in Lambda it is read
    # from Secrets Manager once and exported to the environment by a cold-start
    # hook. Falls back to the secrets integration when not present.
    key = os.environ.get("SESSION_SIGNING_KEY")
    if key:
        return key
    from integrations.secrets import session_signing_key

    return session_signing_key()


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    try:
        return _route(event)
    except ApiError as exc:
        return error(exc.status, exc.message)


def _route(event: dict[str, Any]) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    # auth routes need the Microsoft platform; not wired in this handler yet
    if path.startswith("/api/auth/"):
        raise ApiError(501, "auth routes not implemented")

    # CSRF defence-in-depth: browsers can't set this on a cross-site form post
    if method in ("POST", "PATCH", "DELETE") and "x-requested-with" not in headers:
        raise ApiError(403, "missing X-Requested-With")

    token = read_cookie(headers)
    if not token:
        raise ApiError(401, "not signed in")
    user_id = verify_session(token, _signing_key())

    repo = get_repository()
    segments = [s for s in path.split("/") if s]  # e.g. ["api","applications","a1"]

    return _dispatch(method, segments, user_id, repo, event)


def _dispatch(
    method: str,
    segments: list[str],
    user_id: str,
    repo: Repository,
    event: dict[str, Any],
) -> dict[str, Any]:
    # segments[0] == "api"
    resource = segments[1] if len(segments) > 1 else ""
    rest = segments[2:]

    if resource == "me":
        return _handle_me(method, rest, user_id, repo)
    if resource == "applications":
        return _handle_applications(method, rest, user_id, repo)
    if resource == "analytics":
        return _handle_analytics(user_id, repo, event)
    if resource == "scans":
        return _handle_scans(method, rest, user_id, repo)
    if resource == "deadlines":
        return ok([d.model_dump(mode="json") for d in repo.list_deadlines(user_id)])

    raise ApiError(404, "not found")


def _handle_me(
    method: str, rest: list[str], user_id: str, repo: Repository
) -> dict[str, Any]:
    if rest:
        raise ApiError(404, "not found")
    if method == "GET":
        user = repo.get_user(user_id)
        if user is None:
            raise ApiError(404, "user not found")
        return ok(
            {
                "user_id": user.user_id,
                "email": user.email,
                "name": user.name,
                "status": user.status.value,
                "settings": user.settings.model_dump(mode="json"),
            }
        )
    if method == "DELETE":
        # account deletion (Requirement 14.4); schedule/token/calendar cleanup
        # is enqueued separately by the deletion worker.
        repo.delete_user_data(user_id)
        return no_content()
    raise ApiError(405, "method not allowed")


def _handle_applications(
    method: str, rest: list[str], user_id: str, repo: Repository
) -> dict[str, Any]:
    if not rest:
        if method == "GET":
            apps = repo.list_applications(user_id)
            return ok([a.model_dump(mode="json") for a in apps])
        raise ApiError(405, "method not allowed")

    app_id = rest[0]
    if method == "GET":
        app = repo.get_application(user_id, app_id)
        if app is None:
            raise ApiError(404, "application not found")
        events = repo.list_events(user_id, app_id)
        return ok(
            {
                "application": app.model_dump(mode="json"),
                "timeline": [e.model_dump(mode="json") for e in events],
            }
        )
    raise ApiError(405, "method not allowed")


def _handle_analytics(
    user_id: str, repo: Repository, event: dict[str, Any]
) -> dict[str, Any]:
    apps = repo.list_applications(user_id)
    summary = analytics.summary_counts(apps)
    f = analytics.funnel(apps)
    return ok(
        {
            "summary": {
                "total": summary.total,
                "still_active": summary.still_active,
                "rejected_or_closed": summary.rejected_or_closed,
                "by_status": {k.value: v for k, v in summary.by_status.items()},
                "by_programme": {k.value: v for k, v in summary.by_programme.items()},
            },
            "funnel": {
                "applied": f.applied,
                "assessment": f.assessment,
                "interview": f.interview,
                "final": f.final,
                "offer": f.offer,
                "conversion": f.conversion(),
            },
            "by_firm_type": [
                {
                    "firm_type": r.firm_type.value,
                    "applications": r.applications,
                    "still_active": r.still_active,
                    "rejected_or_closed": r.rejected_or_closed,
                    "got_past_application": r.got_past_application,
                }
                for r in analytics.firm_type_breakdown(apps)
            ],
            "gone_quiet_share": analytics.gone_quiet_share(apps),
            "applications_per_week": analytics.applications_per_week(apps),
        }
    )


def _handle_scans(
    method: str, rest: list[str], user_id: str, repo: Repository
) -> dict[str, Any]:
    if method == "GET" and not rest:
        return ok([s.model_dump(mode="json") for s in repo.list_scans(user_id)])
    if method == "POST" and not rest:
        # "Scan now": enqueue to the scan queue. The queue client is wired at
        # deploy time; enqueue is a thin SQS send and is covered by the scan
        # worker tests. Returns 202-style accepted.
        _enqueue_scan(user_id)
        return created({"status": "queued"})
    raise ApiError(405, "method not allowed")


def _enqueue_scan(user_id: str) -> None:
    import json

    import boto3

    queue_url = os.environ.get("SCAN_QUEUE_URL")
    if not queue_url:
        raise ApiError(503, "scan queue not configured")
    boto3.client("sqs").send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({"user_id": user_id, "trigger": "manual"}),
    )
