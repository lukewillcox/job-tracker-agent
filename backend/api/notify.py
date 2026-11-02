"""Scan-report notifier Lambda (Step Functions step).

Builds the scan-report email in the shape of today's message (X new, Y changes,
new applications, status changes, a To-do list) and sends it via Amazon SES. No
email is sent when nothing changed (Requirement 7.5). An SES failure (e.g. a
sandbox recipient that isn't verified) is logged and swallowed so a scan is
never failed by email delivery.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from aws_lambda_powertools import Logger

from domain.enums import Status
from domain.models import Application
from store.client import get_repository

logger = Logger(service="job-tracker-notify")

_TODO_STATUSES = (Status.CHECK_EMAIL,)
_GONE_QUIET_DAYS = 21


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    new_apps = int(event.get("new_apps", 0))
    status_changes = int(event.get("status_changes", 0))
    if new_apps == 0 and status_changes == 0:
        return {"sent": False, "reason": "no changes"}

    user_id = event["user_id"]
    repo = get_repository()
    user = repo.get_user(user_id)
    if user is None:
        return {"sent": False, "reason": "unknown user"}

    apps = repo.list_applications(user_id)
    subject = f"Job tracker: {new_apps} new, {status_changes} status change(s)"
    body = _build_report(new_apps, status_changes, apps)

    try:
        from integrations.ses import send_email

        message_id = send_email(user.email, subject, body)
        return {"sent": True, "message_id": message_id}
    except Exception as exc:  # SES sandbox / unverified recipient / transient
        # log-only no-op: the dashboard is the source of truth, email is a bonus
        logger.warning("scan report email not sent", extra={"reason": str(exc)[:200]})
        return {"sent": False, "reason": "ses_error"}


def _build_report(new_apps: int, status_changes: int, apps: list[Application]) -> str:
    lines = [f"Your job tracker scan found {new_apps} new and {status_changes} change(s).", ""]

    todo = _todo_items(apps)
    if todo:
        lines.append("To do:")
        lines.extend(f"  - {item}" for item in todo)
        lines.append("")

    lines.append("Open your dashboard to see the details.")
    return "\n".join(lines)


def _todo_items(apps: list[Application]) -> list[str]:
    today = dt.date.today()
    items: list[str] = []
    for app in apps:
        active = app.status in (Status.AWAITING_RESPONSE, Status.ASSESSMENT_STAGE)
        if app.status in _TODO_STATUSES:
            items.append(f"Check email: {app.company}")
        elif active and app.last_update and (today - app.last_update).days >= _GONE_QUIET_DAYS:
            items.append(f"Gone quiet ({(today - app.last_update).days}d): {app.company}")
        if app.next_step and app.next_step not in ("None", None):
            items.append(f"{app.company}: {app.next_step}")
    return items[:20]


# keep logging import usable even if powertools logger is swapped out in tests
_std_logger = logging.getLogger(__name__)
