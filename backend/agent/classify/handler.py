"""Classify Lambda (Step Functions Map step): one Bedrock call per message.

Calls Amazon Bedrock (Converse API, tool use) with the versioned prompt, parses
the result into :class:`domain.models.EmailFacts`, retries once on schema
failure then falls back to ``Check email`` (Requirement 3.6), and resolves any
relative deadline with the implemented, tested
:func:`agent.classify.deadline.resolve_relative_deadline`.

The Bedrock client (`integrations.bedrock`) and the prompt are not implemented
yet because they need live Bedrock access; this documents the contract.
"""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    raise NotImplementedError(
        "integrations.bedrock (Converse tool-use classification) is not implemented "
        "yet; deadline resolution it depends on is implemented in agent.classify.deadline."
    )
