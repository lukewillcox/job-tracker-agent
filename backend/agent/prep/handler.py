"""Prep-pack Lambda: generate an interview prep pack (SQS-driven).

Takes an application whose furthest stage reached Interview or later, calls the
larger Claude model via Bedrock with the PrepPack schema, tags each claim as
coming from the email or general knowledge, and stores the pack.

Needs live Bedrock access (`integrations.bedrock`); this documents the contract.
"""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    raise NotImplementedError(
        "agent.prep prompt + integrations.bedrock are not implemented yet "
        "(needs live Bedrock access)."
    )
