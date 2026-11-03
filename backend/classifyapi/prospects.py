"""Server-side Prospects logic: query generation and the search endpoint.

Pure-ish functions used by the classify Lambda. Bedrock and Brave clients are
injected so this is unit-testable without network. No profile content, query or
result text is ever logged (Requirement 7.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from agent.prompts import load_prompt
from domain.models import ProspectFacts
from integrations.bedrock import BedrockClient
from integrations.brave import BraveClient, SearchResult

QUERY_PROMPT_VERSION = "prospects_queries_v1"
RANK_PROMPT_VERSION = "prospects_rank_v1"
DEFAULT_MONTHLY_CAP = 40
MAX_QUERIES = 6
MIN_QUERIES = 4
MAX_RANK_BATCH = 10
_RESULTS_PER_QUERY = 10
_RANK_TOOL = "record_prospect"

_QUERIES_TOOL = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": MIN_QUERIES,
            "maxItems": MAX_QUERIES,
        }
    },
    "required": ["queries"],
}


@dataclass
class QueryGen:
    queries: list[str]
    input_tokens: int
    output_tokens: int


def _programme_terms(programme: str) -> list[str]:
    if programme == "Graduate":
        return ["graduate"]
    if programme == "Internship":
        return ["internship", "summer internship"]
    return ["graduate", "internship"]


def generate_queries(
    bedrock: BedrockClient, model_id: str, profile: dict[str, Any], max_queries: int
) -> QueryGen:
    """Ask Bedrock for 4-6 queries, then enforce the profile invariants."""

    system = load_prompt(QUERY_PROMPT_VERSION)
    user_text = _profile_text(profile)
    result = bedrock.converse_tool(
        model_id=model_id,
        system=system,
        user_text=user_text,
        tool_name="record_queries",
        tool_description="Record 4-6 web search queries for this profile.",
        tool_schema=_QUERIES_TOOL,
    )
    raw = (result.tool_input or {}).get("queries", []) if result.tool_input else []
    queries = _sanitise_queries(raw, profile, max_queries)
    return QueryGen(queries, result.input_tokens, result.output_tokens)


def _profile_text(profile: dict[str, Any]) -> str:
    def lst(key: str) -> str:
        return ", ".join(profile.get(key) or []) or "(none)"

    return (
        f"Programme: {profile.get('programme', 'Both')}\n"
        f"Start year: {profile.get('start_year', '')}\n"
        f"Degrees: {lst('degrees')}\n"
        f"Skills: {lst('skills')}\n"
        f"Target roles: {lst('target_roles')}\n"
        f"Locations: {lst('locations')}\n"
        f"Exclude: {lst('exclude')}"
    )


def _sanitise_queries(raw: list[Any], profile: dict[str, Any], max_queries: int) -> list[str]:
    """Dedupe, enforce programme wording + start year on every query, and cap."""

    programme = str(profile.get("programme", "Both"))
    year = str(profile.get("start_year", "")).strip()
    terms = _programme_terms(programme)
    roles = profile.get("target_roles") or profile.get("skills") or []
    fallback_role = str(roles[0]) if roles else "analyst"

    out: list[str] = []
    seen: set[str] = set()
    for i, q in enumerate(raw):
        text = str(q).strip()
        if not text:
            continue
        low = text.lower()
        # ensure a programme term is present
        if not any(t in low for t in terms):
            text = f"{terms[i % len(terms)]} {text}"
            low = text.lower()
        # ensure the start year is present
        if year and year not in text:
            text = f"{text} {year}"
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_queries:
            break

    # guarantee at least MIN_QUERIES by synthesising from the profile if the
    # model returned too few. Combine roles with locations/skills so we can
    # always generate enough distinct queries even with a sparse profile.
    if len(out) < MIN_QUERIES:
        role_list = [str(r) for r in roles] or [fallback_role]
        modifiers = [str(m) for m in (profile.get("locations") or [])]
        modifiers += [str(m) for m in (profile.get("skills") or [])]
        modifiers.append("")  # bare role with no modifier
        for term in terms:
            for role in role_list:
                for mod in modifiers:
                    if len(out) >= MIN_QUERIES:
                        break
                    parts = [term, role, mod, year]
                    synth = " ".join(p for p in parts if p).strip()
                    if synth.lower() not in seen:
                        seen.add(synth.lower())
                        out.append(synth)
    return out[:max_queries]


def run_search(
    brave: BraveClient, queries: list[str]
) -> list[SearchResult]:
    """Run all queries and flatten the results."""

    results: list[SearchResult] = []
    for q in queries:
        results.extend(brave.search(q, count=_RESULTS_PER_QUERY))
    return results


# --- ranking -------------------------------------------------------------
@dataclass
class RankedResult:
    url: str
    facts: ProspectFacts


@dataclass
class RankResult:
    prospects: list[RankedResult]
    input_tokens: int
    output_tokens: int


def _rank_tool_schema() -> dict[str, Any]:
    schema = ProspectFacts.model_json_schema()
    schema.pop("title", None)
    return schema


def _rank_one(
    bedrock: BedrockClient,
    model_id: str,
    profile_text: str,
    result: dict[str, Any],
    schema: dict[str, Any],
) -> tuple[ProspectFacts | None, int, int]:
    """Rank one result. Returns (facts|None, in_tokens, out_tokens).

    One retry on schema-validation failure (same pattern as classification);
    then give up and drop the result (caller skips ``None``).
    """

    user_text = (
        f"{profile_text}\n\n"
        f"Result:\n"
        f"Title: {result.get('title', '')}\n"
        f"URL: {result.get('url', '')}\n"
        f"Snippet: {result.get('snippet', '')}\n"
        f"Excerpt: {str(result.get('excerpt', ''))[:4000]}"
    )
    system = load_prompt(RANK_PROMPT_VERSION)
    in_tok = out_tok = 0
    last_error: str | None = None
    for _attempt in range(2):
        prompt = user_text if last_error is None else (
            f"{user_text}\n\nPrevious output was invalid: {last_error}\nReturn valid fields."
        )
        out = bedrock.converse_tool(
            model_id=model_id,
            system=system,
            user_text=prompt,
            tool_name=_RANK_TOOL,
            tool_description="Record extracted facts and a 1-5 fit for one result.",
            tool_schema=schema,
        )
        in_tok += out.input_tokens
        out_tok += out.output_tokens
        if out.tool_input is None:
            last_error = "no tool call returned"
            continue
        try:
            return ProspectFacts.model_validate(out.tool_input), in_tok, out_tok
        except ValidationError as exc:
            last_error = str(exc)[:400]
    return None, in_tok, out_tok


def rank_prospects(
    bedrock: BedrockClient,
    model_id: str,
    profile: dict[str, Any],
    results: list[dict[str, Any]],
) -> RankResult:
    """Extract + score a batch of search results (≤10). Drops unparseable ones."""

    profile_text = _profile_text(profile)
    schema = _rank_tool_schema()
    ranked: list[RankedResult] = []
    total_in = total_out = 0
    for result in results[:MAX_RANK_BATCH]:
        url = str(result.get("url", "")).strip()
        if not url:
            continue
        facts, in_tok, out_tok = _rank_one(bedrock, model_id, profile_text, result, schema)
        total_in += in_tok
        total_out += out_tok
        if facts is not None:
            ranked.append(RankedResult(url=url, facts=facts))
    return RankResult(ranked, total_in, total_out)
