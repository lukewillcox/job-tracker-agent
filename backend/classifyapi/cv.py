"""Server-side CV -> search profile extraction (``POST /profile/extract``).

The CLI reads the user's CV on their Mac, strips contact details, and sends the
remaining text here once. Bedrock drafts a search profile (degrees, skills,
suggested target roles...) which the CLI shows the user to confirm or edit.

Privacy: the CV text is used only for the transient Bedrock call. It is never
stored and never logged; logs carry counts and token totals only.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from agent.prompts import load_prompt
from integrations.bedrock import BedrockClient

CV_PROMPT_VERSION = "profile_extract_v1"
MAX_CV_CHARS = 15000
MIN_CV_CHARS = 200
_MAX_LIST = 8

_PROFILE_TOOL: dict[str, Any] = {
    "type": "object",
    "properties": {
        "programme": {"type": "string", "enum": ["Graduate", "Internship", "Both"]},
        "start_year": {"type": "integer", "minimum": 2000, "maximum": 2100},
        "degrees": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "skills": {"type": "array", "items": {"type": "string"}, "maxItems": _MAX_LIST},
        "target_roles": {"type": "array", "items": {"type": "string"},
                         "maxItems": _MAX_LIST},
        "locations": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
    },
    "required": ["programme", "start_year", "degrees", "skills", "target_roles"],
}


@dataclass
class ProfileDraft:
    profile: dict[str, Any]
    input_tokens: int
    output_tokens: int


def _clean_list(raw: Any, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        text = " ".join(str(item).split())[:80]
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out[:limit]


def sanitise_draft(raw: dict[str, Any] | None, today: dt.date | None = None) -> dict[str, Any]:
    """Coerce the model's output into a valid profile dict (never trusts it)."""

    raw = raw or {}
    today = today or dt.date.today()
    programme = str(raw.get("programme", "Both")).strip().title()
    if programme not in ("Graduate", "Internship", "Both"):
        programme = "Both"
    try:
        year = int(raw.get("start_year", today.year + 1))
    except (TypeError, ValueError):
        year = today.year + 1
    if not today.year - 1 <= year <= today.year + 4:
        year = today.year + 1
    return {
        "programme": programme,
        "start_year": year,
        "degrees": _clean_list(raw.get("degrees"), 4),
        "skills": _clean_list(raw.get("skills"), _MAX_LIST),
        "target_roles": _clean_list(raw.get("target_roles"), _MAX_LIST),
        "locations": _clean_list(raw.get("locations"), 4),
    }


def extract_profile(
    bedrock: BedrockClient, model_id: str, cv_text: str, today: dt.date | None = None
) -> ProfileDraft:
    """Draft a search profile from CV text (already stripped of contact details)."""

    today = today or dt.date.today()
    result = bedrock.converse_tool(
        model_id=model_id,
        system=load_prompt(CV_PROMPT_VERSION),
        user_text=f"Today: {today.isoformat()}\n\nCV:\n{cv_text[:MAX_CV_CHARS]}",
        tool_name="record_profile",
        tool_description="Record a draft job-search profile drawn from this CV.",
        tool_schema=_PROFILE_TOOL,
    )
    return ProfileDraft(
        sanitise_draft(result.tool_input, today), result.input_tokens, result.output_tokens
    )
