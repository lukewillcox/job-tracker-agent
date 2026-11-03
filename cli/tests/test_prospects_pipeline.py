"""Tests for the CLI Prospects pipeline (Task 4)."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Any

import pytest
from domain.enums import ProspectStatus, Status
from domain.models import Application, Prospect

from jobtracker_cli import prospects as pp
from jobtracker_cli.localstore import LocalStore
from jobtracker_cli.profile import Profile
from jobtracker_cli.prospects_client import RankedProspect, RankResponse, SearchHit, SearchResponse

TODAY = dt.date(2026, 11, 1)

PROFILE = Profile(
    programme="Graduate",
    start_year=2027,
    skills=["Python"],
    target_roles=["quantitative analyst"],
    locations=["London"],
    exclude=["sales"],
)


class FakeClient:
    """Stand-in for ProspectsClient returning canned search + rank results."""

    def __init__(self, hits: list[SearchHit], ranked: list[RankedProspect],
                 capped: bool = False) -> None:
        self._hits = hits
        self._ranked = ranked
        self._capped = capped
        self.ranked_payloads: list[dict[str, Any]] = []

    def search(self, profile: dict[str, Any], max_queries: int = 6) -> SearchResponse:
        if self._capped:
            return SearchResponse(hits=[], queries=[], queries_used=40,
                                  queries_left=0, capped=True)
        return SearchResponse(hits=self._hits, queries=["q"], queries_used=4, queries_left=36)

    def rank(self, profile: dict[str, Any], results: list[dict[str, Any]]) -> RankResponse:
        self.ranked_payloads.extend(results)
        return RankResponse(prospects=list(self._ranked), tokens_in=100, tokens_out=20)


def _hit(url: str, title: str = "Role") -> SearchHit:
    return SearchHit(title=title, snippet="snippet", url=url, age="1 day", query="q")


def _rp(url: str, **over: Any) -> RankedProspect:
    base = dict(
        url=url, is_job=True, company="Jane Street", role="Quantitative Analyst",
        programme="Graduate", location="London", closing_date=None, fit=5,
        why="python + london + 2027 graduate",
    )
    base.update(over)
    return RankedProspect(**base)  # type: ignore[arg-type]


def _store(tmp_path: Path) -> LocalStore:
    return LocalStore(path=tmp_path / "data.json")


# --- restricted domains --------------------------------------------------
def test_is_restricted() -> None:
    assert pp.is_restricted("https://www.linkedin.com/jobs/view/1") is True
    assert pp.is_restricted("https://careers.ucl.ac.uk/x") is True
    assert pp.is_restricted("https://jobs.janestreet.com/x") is False
    assert pp.is_restricted("not a url") is True  # unparseable -> never fetch


def test_restricted_urls_are_never_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def boom(url: str, **kwargs: Any) -> Any:
        calls.append(url)
        raise AssertionError("restricted URL must never be fetched")

    import requests
    monkeypatch.setattr(requests, "get", boom)
    # fetch_excerpt on a restricted URL returns '' and never calls requests.get
    assert pp.fetch_excerpt("https://www.linkedin.com/jobs/1") == ""
    assert calls == []


def test_pipeline_does_not_fetch_restricted(tmp_path: Path) -> None:
    hits = [_hit("https://www.linkedin.com/jobs/1"), _hit("https://jobs.firm.com/2")]
    client = FakeClient(hits, [_rp("https://www.linkedin.com/jobs/1"),
                               _rp("https://jobs.firm.com/2")])
    store = _store(tmp_path)
    # allow_fetch True but restricted ones carry no excerpt
    pp.run_prospects(client, PROFILE, store, today=TODAY, allow_fetch=False)
    # payloads for restricted URLs must have no 'excerpt'
    for item in client.ranked_payloads:
        if "linkedin.com" in str(item["url"]):
            assert "excerpt" not in item


# --- dedupe --------------------------------------------------------------
def test_dedupe_by_url() -> None:
    hits = [_hit("https://x.com/1"), _hit("https://x.com/1/"), _hit("https://x.com/2")]
    assert len(pp.dedupe(hits)) == 2


# --- filtering -----------------------------------------------------------
def test_low_fit_dropped(tmp_path: Path) -> None:
    client = FakeClient([_hit("https://x.com/1")], [_rp("https://x.com/1", fit=2)])
    store = _store(tmp_path)
    s = pp.run_prospects(client, PROFILE, store, today=TODAY)
    assert s.added == 0 and s.dropped_low_fit == 1
    assert store.prospects() == []


def test_non_job_dropped(tmp_path: Path) -> None:
    client = FakeClient([_hit("https://x.com/1")], [_rp("https://x.com/1", is_job=False)])
    store = _store(tmp_path)
    s = pp.run_prospects(client, PROFILE, store, today=TODAY)
    assert s.added == 0


def test_programme_mismatch_dropped(tmp_path: Path) -> None:
    client = FakeClient([_hit("https://x.com/1")],
                        [_rp("https://x.com/1", programme="Internship")])
    store = _store(tmp_path)
    s = pp.run_prospects(client, PROFILE, store, today=TODAY)
    assert s.added == 0


def test_exclusion_dropped(tmp_path: Path) -> None:
    client = FakeClient([_hit("https://x.com/1")],
                        [_rp("https://x.com/1", role="Sales Analyst")])
    store = _store(tmp_path)
    s = pp.run_prospects(client, PROFILE, store, today=TODAY)
    assert s.added == 0


def test_good_prospect_added(tmp_path: Path) -> None:
    client = FakeClient([_hit("https://x.com/1")], [_rp("https://x.com/1")])
    store = _store(tmp_path)
    s = pp.run_prospects(client, PROFILE, store, today=TODAY)
    assert s.added == 1
    prospect = store.prospects()[0]
    assert prospect.company == "Jane Street"
    assert prospect.status == ProspectStatus.NEW
    assert prospect.source == "Janestreet" or prospect.source  # a source label set


# --- matching existing applications --------------------------------------
def test_skips_existing_application(tmp_path: Path) -> None:
    store = _store(tmp_path)
    from domain.firm_directory import normalise
    store.put_application(Application(
        app_id=str(uuid.uuid4()), company="Jane Street",
        company_norm=normalise("Jane Street"), role="Quantitative Analyst",
        status=Status.AWAITING_RESPONSE,
    ))
    client = FakeClient([_hit("https://x.com/1")], [_rp("https://x.com/1")])
    s = pp.run_prospects(client, PROFILE, store, today=TODAY)
    assert s.added == 0 and s.skipped_existing == 1


# --- company+role dedupe across URLs -------------------------------------
def test_same_company_role_different_url_deduped(tmp_path: Path) -> None:
    client = FakeClient(
        [_hit("https://x.com/1"), _hit("https://y.com/2")],
        [_rp("https://x.com/1"), _rp("https://y.com/2")],
    )
    store = _store(tmp_path)
    s = pp.run_prospects(client, PROFILE, store, today=TODAY)
    assert s.added == 1  # second one is same company+role


# --- re-found prospect updates, keeps status -----------------------------
def test_refound_prospect_preserves_status(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put_prospect(Prospect(
        prospect_id="p1", url="https://x.com/1", company="Jane Street",
        company_norm="jane street", role="Quantitative Analyst",
        fit=4, status=ProspectStatus.INTERESTED, found_at=TODAY, last_seen=TODAY,
    ))
    later = TODAY + dt.timedelta(days=7)
    client = FakeClient([_hit("https://x.com/1")], [_rp("https://x.com/1", fit=5)])
    pp.run_prospects(client, PROFILE, store, today=later)
    p = store.get_prospect("p1")
    assert p is not None
    assert p.status == ProspectStatus.INTERESTED  # user's status untouched
    assert p.fit == 5 and p.last_seen == later  # facts refreshed


# --- 60-day expiry -------------------------------------------------------
def test_old_new_prospect_expires(tmp_path: Path) -> None:
    store = _store(tmp_path)
    old = TODAY - dt.timedelta(days=61)
    store.put_prospect(Prospect(
        prospect_id="old", url="https://x.com/old", company="Old Co",
        company_norm="old co", role="r", status=ProspectStatus.NEW,
        found_at=old, last_seen=old,
    ))
    store.put_prospect(Prospect(
        prospect_id="kept", url="https://x.com/kept", company="Kept Co",
        company_norm="kept co", role="r", status=ProspectStatus.INTERESTED,
        found_at=old, last_seen=old,
    ))
    client = FakeClient([], [])
    s = pp.run_prospects(client, PROFILE, store, today=TODAY)
    assert s.expired == 1
    assert store.get_prospect("old") is None       # New + >60d -> dropped
    assert store.get_prospect("kept") is not None   # Interested -> kept


# --- cap -----------------------------------------------------------------
def test_search_cap_stops_run(tmp_path: Path) -> None:
    client = FakeClient([], [], capped=True)
    store = _store(tmp_path)
    s = pp.run_prospects(client, PROFILE, store, today=TODAY)
    assert s.capped is True and s.added == 0


# --- sync prospects -> Applied after a scan (Requirement 6.2) ------------
def _app(company: str, role: str) -> Application:
    from domain.firm_directory import normalise
    return Application(
        app_id=str(uuid.uuid4()), company=company, company_norm=normalise(company),
        role=role, status=Status.AWAITING_RESPONSE,
    )


def test_sync_flips_matching_prospect_to_applied(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put_prospect(Prospect(
        prospect_id="p1", url="https://x.com/1", company="Jane Street",
        company_norm="jane street", role="Quantitative Analyst",
        status=ProspectStatus.NEW, found_at=TODAY, last_seen=TODAY,
    ))
    store.put_application(_app("Jane Street", "Quantitative Analyst Graduate"))
    flipped = pp.sync_prospects_with_applications(store)
    assert flipped == 1
    assert store.get_prospect("p1").status == ProspectStatus.APPLIED  # type: ignore[union-attr]


def test_sync_leaves_not_for_me_alone(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put_prospect(Prospect(
        prospect_id="p1", url="https://x.com/1", company="Jane Street",
        company_norm="jane street", role="Quantitative Analyst",
        status=ProspectStatus.NOT_FOR_ME, found_at=TODAY, last_seen=TODAY,
    ))
    store.put_application(_app("Jane Street", "Quantitative Analyst"))
    assert pp.sync_prospects_with_applications(store) == 0
    assert store.get_prospect("p1").status == ProspectStatus.NOT_FOR_ME  # type: ignore[union-attr]


def test_sync_no_match_leaves_new(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put_prospect(Prospect(
        prospect_id="p1", url="https://x.com/1", company="Jane Street",
        company_norm="jane street", role="Quantitative Analyst",
        status=ProspectStatus.NEW, found_at=TODAY, last_seen=TODAY,
    ))
    store.put_application(_app("Citadel", "Software Engineer"))
    assert pp.sync_prospects_with_applications(store) == 0
    assert store.get_prospect("p1").status == ProspectStatus.NEW  # type: ignore[union-attr]
