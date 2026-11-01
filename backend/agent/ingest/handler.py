"""Ingest Lambda (Step Functions step): Graph delta sync + prefilter.

Pulls new/changed messages from Microsoft Graph since the saved delta link,
runs the (implemented, tested) :func:`agent.ingest.prefilter.prefilter` over
sender/subject/preview, fetches full bodies only for messages that pass, strips
signatures/quotes and truncates to 4,000 chars, and returns the shortlist for
the classify step. Bodies never leave Lambda memory and are never persisted.

The Graph delta client (`agent.ingest.delta`) is not implemented yet because it
needs live Microsoft Graph access; this entry point documents the contract and
raises until that client lands.
"""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    _user_id = event["user_id"]
    raise NotImplementedError(
        "agent.ingest.delta (Microsoft Graph delta sync) is not implemented yet; "
        "the prefilter it feeds is implemented and tested in agent.ingest.prefilter."
    )
