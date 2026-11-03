"""Tests for the server-side Prospects search (Task 2)."""

from __future__ import annotations

from typing import Any

from classifyapi.prospects import generate_queries, rank_prospects, run_search
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


class _RankBedrock(BedrockClient):
    """Returns a queued tool_input per converse_tool call."""

    def __init__(self, outputs: list[dict[str, Any] | None]) -> None:
        self._outputs = list(outputs)
        self.calls = 0

    def converse_tool(self, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        out = self._outputs.pop(0) if self._outputs else None
        self.calls += 1
        return ToolResult(
            tool_input=out,
            input_tokens=200,
            output_tokens=30,
            stop_reason="tool_use",
        )


def _good_facts(**over: Any) -> dict[str, Any]:
    base = {
        "is_job": True,
        "company": "Jane Street",
        "role": "Quantitative Trader",
        "programme": "Graduate",
        "location": "London",
        "closing_date": None,
        "fit": 5,
        "why": "quant + London + 2027 graduate",
    }
    base.update(over)
    return base


def test_rank_prospects_extracts_each_result() -> None:
    bedrock = _RankBedrock([_good_facts(), _good_facts(company="Citadel", fit=4)])
    results = [
        {"title": "a", "url": "https://x.com/1", "snippet": "s"},
        {"title": "b", "url": "https://x.com/2", "snippet": "s"},
    ]
    out = rank_prospects(bedrock, "model-x", PROFILE, results)
    assert len(out.prospects) == 2
    assert out.prospects[0].url == "https://x.com/1"
    assert out.prospects[0].facts.company == "Jane Street"
    assert out.input_tokens == 400  # 200 per result
    assert out.output_tokens == 60


def test_rank_prospects_skips_results_without_url() -> None:
    bedrock = _RankBedrock([_good_facts()])
    results = [{"title": "no url", "snippet": "s"}, {"url": "https://x.com/2"}]
    out = rank_prospects(bedrock, "model-x", PROFILE, results)
    assert len(out.prospects) == 1
    assert out.prospects[0].url == "https://x.com/2"


def test_rank_prospects_retries_once_then_drops_invalid() -> None:
    # first result: invalid both attempts (fit out of range) -> dropped;
    # second result: valid first try.
    bad = {"is_job": True, "fit": 9, "why": "x"}
    bedrock = _RankBedrock([bad, bad, _good_facts()])
    results = [{"url": "https://x.com/1"}, {"url": "https://x.com/2"}]
    out = rank_prospects(bedrock, "model-x", PROFILE, results)
    assert len(out.prospects) == 1
    assert out.prospects[0].url == "https://x.com/2"
    assert bedrock.calls == 3  # 2 retries on the bad one + 1 on the good one


def test_rank_prospects_caps_batch_at_ten() -> None:
    bedrock = _RankBedrock([_good_facts() for _ in range(20)])
    results = [{"url": f"https://x.com/{i}"} for i in range(20)]
    out = rank_prospects(bedrock, "model-x", PROFILE, results)
    assert len(out.prospects) == 10
    assert bedrock.calls == 10


def test_freshness_follows_profile_recency() -> None:
    from classifyapi.prospects import freshness_for

    assert freshness_for({"recency": "week"}) == "pw"
    assert freshness_for({"recency": "month"}) == "pm"
    assert freshness_for({}) == "pm"


def test_about_reaches_the_model_and_both_means_month() -> None:
    from classifyapi.prospects import _profile_text, freshness_for

    text = _profile_text({"about": "rates or FX trading at a bank", "programme": "Graduate"})
    assert "rates or FX trading at a bank" in text
    assert "(not given)" in _profile_text({})
    assert freshness_for({"recency": "both"}) == "pm"
