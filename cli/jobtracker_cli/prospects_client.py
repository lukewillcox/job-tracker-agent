"""Client for the host's Prospects API (search + rank).

Mirrors :class:`ClassifyClient`: the invite code is a Bearer token, the profile
is sent only inside the request (never stored server-side), and transient
gateway errors are retried. ``/prospects/rank`` is called in batches of 10 to
stay under the API Gateway timeout.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

from jobtracker_cli.classify_client import ClassifyApiError, _safe_error

_RANK_BATCH = 10
_SEARCH_TIMEOUT = 40
_RANK_TIMEOUT = 40


@dataclass
class SearchHit:
    title: str
    snippet: str
    url: str
    age: str | None
    query: str
    page_age: str | None = None


@dataclass
class SearchResponse:
    hits: list[SearchHit]
    queries: list[str]
    queries_used: int
    queries_left: int
    capped: bool = False


@dataclass
class RankedProspect:
    url: str
    is_job: bool
    company: str | None
    role: str | None
    programme: str
    location: str | None
    closing_date: str | None
    fit: int
    why: str
    opening_date: str | None = None


@dataclass
class RankResponse:
    prospects: list[RankedProspect] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


class ProspectsClient:
    def __init__(self, api_url: str, invite_code: str) -> None:
        self._base = api_url.rstrip("/")
        self._code = invite_code

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._code}",
            "Content-Type": "application/json",
        }

    def search(self, profile: dict[str, Any], max_queries: int = 6) -> SearchResponse:
        resp = self._post(
            self._base + "/prospects/search",
            {"profile": profile, "max_queries": max_queries},
            _SEARCH_TIMEOUT,
        )
        if resp.status_code == 429:
            d = _json(resp)
            return SearchResponse(
                hits=[], queries=[],
                queries_used=int(d.get("queries_used", 0)),
                queries_left=0, capped=True,
            )
        if resp.status_code != 200:
            raise ClassifyApiError(resp.status_code, _safe_error(resp))
        d = _json(resp)
        hits = [
            SearchHit(
                title=str(r.get("title", "")),
                snippet=str(r.get("snippet", "")),
                url=str(r.get("url", "")),
                age=r.get("age"),
                query=str(r.get("query", "")),
                page_age=r.get("page_age"),
            )
            for r in d.get("results", [])
            if r.get("url")
        ]
        return SearchResponse(
            hits=hits,
            queries=list(d.get("queries", [])),
            queries_used=int(d.get("queries_used", 0)),
            queries_left=int(d.get("queries_left", 0)),
        )

    def rank(self, profile: dict[str, Any], results: list[dict[str, Any]]) -> RankResponse:
        out = RankResponse()
        for i in range(0, len(results), _RANK_BATCH):
            batch = results[i : i + _RANK_BATCH]
            resp = self._post(
                self._base + "/prospects/rank",
                {"profile": profile, "results": batch},
                _RANK_TIMEOUT,
            )
            if resp.status_code in (401, 403, 429):
                raise ClassifyApiError(resp.status_code, _safe_error(resp))
            if resp.status_code != 200:
                # skip this batch rather than aborting the whole run
                continue
            d = _json(resp)
            for p in d.get("prospects", []):
                out.prospects.append(
                    RankedProspect(
                        url=str(p.get("url", "")),
                        is_job=bool(p.get("is_job")),
                        company=p.get("company"),
                        role=p.get("role"),
                        programme=str(p.get("programme", "Not stated")),
                        location=p.get("location"),
                        closing_date=p.get("closing_date"),
                        fit=int(p.get("fit", 1)),
                        why=str(p.get("why", "")),
                        opening_date=p.get("opening_date"),
                    )
                )
            out.tokens_in += int(d.get("tokens_in", 0))
            out.tokens_out += int(d.get("tokens_out", 0))
        return out

    def _post(self, url: str, body: dict[str, Any], timeout: int) -> requests.Response:
        last: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(url, headers=self._headers(), json=body, timeout=timeout)
            except requests.RequestException as exc:
                last = exc
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code in (502, 503, 504):
                last = ClassifyApiError(resp.status_code, _safe_error(resp))
                time.sleep(2 * (attempt + 1))
                continue
            return resp
        raise ClassifyApiError(503, f"request failed after retries: {last}")


def _json(resp: requests.Response) -> dict[str, Any]:
    try:
        data: dict[str, Any] = resp.json()
        return data
    except ValueError:
        return {}
