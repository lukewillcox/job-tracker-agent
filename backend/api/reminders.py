"""Reminder sweeper Lambda (EventBridge, every 15 minutes).

Queries the current GSI1 reminder bucket, groups due items per user into one SES
email, and marks each reminder sent with an idempotent conditional write
(Requirement 8.3, design.md "Deadlines and reminders").

Needs SES (`integrations.ses`); this documents the contract.
"""

from __future__ import annotations

from typing import Any


def sweeper_handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    raise NotImplementedError(
        "reminder sweeper needs integrations.ses and the GSI1 bucket query "
        "(precomputed remind_at); not implemented yet."
    )
