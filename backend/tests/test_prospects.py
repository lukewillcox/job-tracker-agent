"""Tests for the server-side Prospects search (Task 2)."""

from __future__ import annotations

from typing import Any

from classifyapi.prospects import generate_queries, run_search
from integrations.bedrock import BedrockClient, ToolResult
from integrations.brave import BraveClient, SearchResult

PROFILE = {
    "programme": "Graduate",
    "start_year": 2027,
    "degrees": ["MSc Quantum Technologies"],
    "skills": ["Python", "statistics"],
    "target_roles": ["quantitative analyst", "trader"],
    "locations": ["London"],
    "exclude": ["sales"],
}


class _FakeBedrock(BedrockClient):
    def __init__(self, queries: list[str]) -> None:
        self._queries = queries

    def converse_tool(self, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        return ToolResult(
            tool_input={"queries": self._queries},
            input_tokens=300,
            output_tokens=40,
            stop_reason="tool_use",
        )


class _FakeBrave(BraveClient):
    def __init__(self) -> None:
        self.queries_run: list[str] = []

    def search(self, query: str, count: int = 10, freshness: str = "pm") -> list[SearchResult]:
        self.queries_run.append(query)
        return [
            SearchResult(
                title=f"{query} result",
                snippet="a job",
                url=f"https://jobs.example.com/{len(self.queries_run)}",
                age="2 days",
                query=query,
            )
        ]


def test_generate_queries_enforces_programme_and_year() -> None:
    # model returns queries missing the programme term and the year
    bedrock = _FakeBedrock(["quantitative analyst London", "trader roles"])
    gen = generate_queries(bedrock, "model-x", PROFILE, max_queries=6)
    assert 4 <= len(gen.queries) <= 6
    for q in gen.queries:
        assert "graduate" in q.lower()  # programme term injected
        assert "2027" in q  # start year injected


def test_generate_queries_dedupes() -> None:
    bedrock = _FakeBedrock(["graduate trader 2027", "graduate trader 2027", "graduate quant 2027"])
    gen = generate_queries(bedrock, "model-x", PROFILE, max_queries=6)
    assert len(gen.queries) == len(set(q.lower() for q in gen.queries))


def test_generate_queries_min_four_even_if_model_returns_fewer() -> None:
    bedrock = _FakeBedrock(["graduate quant 2027"])
    gen = generate_queries(bedrock, "model-x", PROFILE, max_queries=6)
    assert len(gen.queries) >= 4  # synthesised from target_roles


def test_generate_queries_respects_max() -> None:
    many = [f"graduate role{i} 2027" for i in range(10)]
    gen = generate_queries(_FakeBedrock(many), "model-x", PROFILE, max_queries=5)
    assert len(gen.queries) == 5


def test_internship_programme_terms() -> None:
    profile = {**PROFILE, "programme": "Internship"}
    gen = generate_queries(_FakeBedrock(["quant role"]), "model-x", profile, max_queries=6)
    assert all("internship" in q.lower() for q in gen.queries)


def test_run_search_flattens_results() -> None:
    brave = _FakeBrave()
    results = run_search(brave, ["q1", "q2", "q3"])
    assert len(brave.queries_run) == 3
    assert len(results) == 3
    assert all(r.url.startswith("https://") for r in results)
