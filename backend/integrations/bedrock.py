"""Amazon Bedrock client (Converse API with tool use).

Wraps a single Converse call that forces the model to return its answer through
one tool whose input schema is supplied by the caller. The model id comes from
configuration (``CLASSIFIER_MODEL_ID`` / ``PREP_MODEL_ID``), never hard-coded
(tech.md). Token usage is returned for per-scan cost accounting.

The boto3 client is injectable so the classifier is unit-testable without
calling Bedrock.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import boto3


@dataclass
class ToolResult:
    """The parsed tool input the model returned, plus token usage."""

    tool_input: dict[str, Any] | None
    input_tokens: int
    output_tokens: int
    stop_reason: str


@lru_cache(maxsize=1)
def _default_client() -> Any:
    return boto3.client("bedrock-runtime")


class BedrockClient:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client or _default_client()

    def converse_tool(
        self,
        *,
        model_id: str,
        system: str,
        user_text: str,
        tool_name: str,
        tool_description: str,
        tool_schema: dict[str, Any],
        temperature: float = 0.0,
    ) -> ToolResult:
        """Run one Converse call that must answer via ``tool_name``."""

        resp = self._client.converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user_text}]}],
            inferenceConfig={"temperature": temperature},
            toolConfig={
                "tools": [
                    {
                        "toolSpec": {
                            "name": tool_name,
                            "description": tool_description,
                            "inputSchema": {"json": tool_schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": tool_name}},
            },
        )
        return _parse(resp, tool_name)


def _parse(resp: dict[str, Any], tool_name: str) -> ToolResult:
    usage = resp.get("usage", {})
    tool_input: dict[str, Any] | None = None
    for block in resp.get("output", {}).get("message", {}).get("content", []):
        use = block.get("toolUse")
        if use and use.get("name") == tool_name:
            tool_input = use.get("input")
            break
    return ToolResult(
        tool_input=tool_input,
        input_tokens=int(usage.get("inputTokens", 0)),
        output_tokens=int(usage.get("outputTokens", 0)),
        stop_reason=resp.get("stopReason", ""),
    )
