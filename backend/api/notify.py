"""Scan-report notifier Lambda (Step Functions step).

Builds the scan-report email in the shape of today's message (X new, Y changes,
new applications, status changes, a To-do list) from the scan result and the
user's data, and sends it via Amazon SES. No email is sent when nothing changed
(Requirement 7.5).

Needs SES (`integrations.ses`); this documents the contract.
"""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    new_apps = event.get("new_apps", 0)
    status_changes = event.get("status_changes", 0)
    if new_apps == 0 and status_changes == 0:
        return {"sent": False, "reason": "no changes"}
    raise NotImplementedError(
        "integrations.ses (scan report email) is not implemented yet (needs SES)."
    )
