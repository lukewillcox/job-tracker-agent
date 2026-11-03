"""The weekly Prospects pipeline (client side).

search (host) -> dedupe -> restricted-domain guard -> optional single page
fetch -> rank (host) -> filter -> sync into the local store.

Restricted sites (LinkedIn, university careers portals) are NEVER fetched
(Requirement 3.1): they are ranked from title + snippet only. Other pages may be
fetched once, with a clear User-Agent, a 10s timeout and no retries, purely to
fill in missing facts before ranking (Requirement 3.3).

No profile, query or result text is logged here; the host logs counts only.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from agent.match.normalise import normalise_company, normalise_role, token_set_ratio
from domain.enums import Programme, ProspectStatus
from domain.models import Application, Prospect

from jobtracker_cli.localstore import LocalStore
from jobtracker_cli.profile import Profile
from jobtracker_cli.prospects_client import ProspectsClient, RankedProspect, SearchHit

# Sites that require a login or forbid automated access. Never fetched; still
# added as prospects from the snippet (Requirement 3). Configurable here.
RESTRICTED_DOMAINS: tuple[str, ...] = (
    "linkedin.com",
    "ucl.ac.uk",
    "myuclcareers.com",
    "targetconnect.net",  # common UK university careers portal backend
    "joinhandshake.com",
    "handshake.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
)

MIN_FIT = 3
_FETCH_TIMEOUT = 10
_FETCH_MAX_CHARS = 4000
_NEW_EXPIRY_DAYS = 60
_ROLE_MATCH_THRESHOLD = 0.8
_USER_AGENT = "jobtracker/1.0 (+https://github.com/lukewillcox/job-tracker-agent)"


@dataclass
class ProspectsSummary:
    searched: int = 0
    queries_used: int = 0
    queries_left: int = 0
    capped: bool = False
    ranked: int = 0
    added: int = 0
    skipped_existing: int = 0
    dropped_low_fit: int = 0
    expired: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    note: str = ""


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_restricted(url: str) -> bool:
    """True if the URL's host is on (or under) a restricted domain."""

    host = _host(url)
    if not host:
        return True  # unparseable -> treat as restricted (never fetch)
    return any(host == d or host.endswith("." + d) for d in RESTRICTED_DOMAINS)


def source_name(url: str) -> str:
    """A short human label for the Source column (the site's registrable name)."""

    host = _host(url)
    if not host:
        return ""
    parts = host.removeprefix("www.").split(".")
    return parts[-2].capitalize() if len(parts) >= 2 else host


def dedupe(hits: list[SearchHit]) -> list[SearchHit]:
    """Merge duplicate hits by URL (Requirement 2.6, URL half).

    Company+role dedupe happens after ranking, when those facts exist.
    """

    seen: set[str] = set()
    out: list[SearchHit] = []
    for h in hits:
        key = h.url.split("#", 1)[0].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def fetch_excerpt(url: str, fetcher: object | None = None) -> str:
    """Fetch one non-restricted page once (10s, no retries). '' on any failure.

    ``is_restricted`` is checked by the caller, but we re-check here as a hard
    guard so a restricted URL can never be fetched even if mis-called.
    """

    if is_restricted(url):
        return ""
    import requests

    try:
        get = fetcher or requests.get
        resp = get(  # type: ignore[operator]
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_FETCH_TIMEOUT,
            allow_redirects=True,
        )
        if getattr(resp, "status_code", 0) != 200:
            return ""
        text = _strip_html(resp.text)
        return text[:_FETCH_MAX_CHARS]
    except Exception:  # noqa: BLE001 — a page fetch must never break a run
        return ""


def _strip_html(html: str) -> str:
    import re

    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _programme_matches(profile: Profile, prog: str) -> bool:
    if profile.programme == "Both":
        return prog in (Programme.GRADUATE.value, Programme.INTERNSHIP.value,
                        Programme.NOT_STATED.value)
    # Not stated is allowed through; a strict mismatch is dropped
    return prog in (profile.programme, Programme.NOT_STATED.value)


def _hits_exclusion(profile: Profile, rp: RankedProspect) -> bool:
    hay = f"{rp.role or ''} {rp.company or ''} {rp.why}".lower()
    return any(ex.strip().lower() in hay for ex in profile.exclude if ex.strip())


def _matches_application(rp: RankedProspect, apps: list[Application]) -> bool:
    """True if this prospect is one the user has already applied for (Req 6.1)."""

    comp = normalise_company(rp.company or "")
    role = normalise_role(rp.role)
    if not comp:
        return False
    for app in apps:
        if app.company_norm != comp:
            continue
        if not role or not app.role:
            return True  # same company, role unknown -> treat as the same
        if token_set_ratio(role, normalise_role(app.role)) >= _ROLE_MATCH_THRESHOLD:
            return True
    return False


def _to_programme(value: str) -> Programme:
    try:
        return Programme(value)
    except ValueError:
        return Programme.NOT_STATED


def _parse_date(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def run_prospects(
    client: ProspectsClient,
    profile: Profile,
    store: LocalStore,
    *,
    today: dt.date | None = None,
    allow_fetch: bool = True,
) -> ProspectsSummary:
    """Run one prospects pass end to end and persist the results."""

    today = today or dt.datetime.now(dt.UTC).date()
    summary = ProspectsSummary()

    search = client.search(profile.model_dump(mode="json"))
    summary.queries_used = search.queries_used
    summary.queries_left = search.queries_left
    if search.capped:
        summary.capped = True
        summary.note = "monthly search cap reached"
        _expire_old(store, today, summary)
        store.save()
        return summary

    hits = dedupe(search.hits)
    summary.searched = len(hits)
    if not hits:
        _expire_old(store, today, summary)
        store.save()
        return summary

    # build rank payloads; fetch an excerpt only for non-restricted pages
    payloads: list[dict[str, object]] = []
    for h in hits:
        item: dict[str, object] = {"title": h.title, "snippet": h.snippet, "url": h.url}
        if allow_fetch and not is_restricted(h.url):
            excerpt = fetch_excerpt(h.url)
            if excerpt:
                item["excerpt"] = excerpt
        payloads.append(item)

    ranked = client.rank(profile.model_dump(mode="json"), payloads)
    summary.ranked = len(ranked.prospects)
    summary.tokens_in = ranked.tokens_in
    summary.tokens_out = ranked.tokens_out

    apps = store.applications()
    _sync(store, profile, ranked.prospects, apps, today, summary)
    _expire_old(store, today, summary)
    store.save()
    return summary


def _sync(
    store: LocalStore,
    profile: Profile,
    ranked: list[RankedProspect],
    apps: list[Application],
    today: dt.date,
    summary: ProspectsSummary,
) -> None:
    # URL -> existing prospect, so a re-found role updates rather than duplicates
    by_url = {p.url.rstrip("/").lower(): p for p in store.prospects()}
    # company+role key for the non-URL dedupe (Requirement 2.6)
    seen_company_role: set[tuple[str, str]] = {
        (p.company_norm, normalise_role(p.role)) for p in store.prospects()
    }

    for rp in ranked:
        if not rp.is_job:
            continue
        if rp.fit < MIN_FIT:
            summary.dropped_low_fit += 1
            continue
        if not _programme_matches(profile, rp.programme):
            continue
        if _hits_exclusion(profile, rp):
            continue
        if _matches_application(rp, apps):
            summary.skipped_existing += 1
            continue

        url_key = rp.url.rstrip("/").lower()
        existing = by_url.get(url_key)
        if existing is not None:
            # refresh facts + last_seen but never clobber a user's Status edit
            _refresh(store, existing, rp, today)
            continue

        cr_key = (normalise_company(rp.company or ""), normalise_role(rp.role))
        if cr_key[0] and cr_key in seen_company_role:
            continue  # same company+role already tracked under another URL
        seen_company_role.add(cr_key)

        store.put_prospect(_new_prospect(rp, today))
        summary.added += 1


def _new_prospect(rp: RankedProspect, today: dt.date) -> Prospect:
    return Prospect(
        prospect_id=str(uuid.uuid4()),
        url=rp.url,
        company=rp.company,
        company_norm=normalise_company(rp.company or ""),
        role=rp.role,
        programme=_to_programme(rp.programme),
        location=rp.location,
        closing_date=_parse_date(rp.closing_date),
        fit=rp.fit,
        why=rp.why,
        source=source_name(rp.url),
        status=ProspectStatus.NEW,
        found_at=today,
        last_seen=today,
    )


def _refresh(store: LocalStore, existing: Prospect, rp: RankedProspect, today: dt.date) -> None:
    """Update a re-found prospect's facts and last_seen, preserving Status edits."""

    updated = existing.model_copy(
        update={
            "last_seen": today,
            "fit": rp.fit,
            "why": rp.why,
            "closing_date": _parse_date(rp.closing_date) or existing.closing_date,
        }
    )
    store.put_prospect(updated)


def _expire_old(store: LocalStore, today: dt.date, summary: ProspectsSummary) -> None:
    """Drop prospects still New after 60 days (Requirement 5.6)."""

    cutoff = today - dt.timedelta(days=_NEW_EXPIRY_DAYS)
    for p in list(store.prospects()):
        if p.status == ProspectStatus.NEW and p.found_at < cutoff:
            store.drop_prospect(p.prospect_id)
            summary.expired += 1


def sync_prospects_with_applications(store: LocalStore) -> int:
    """Flip prospects to Applied when the tracker has a matching application.

    Called after each `scan` (Requirement 6.2). Matches on normalised company +
    fuzzy role, the same rule used to skip new prospects. A prospect the user
    marked "Not for me" is left alone. Returns the number flipped.
    """

    apps = store.applications()
    flipped = 0
    for p in store.prospects():
        if p.status in (ProspectStatus.APPLIED, ProspectStatus.NOT_FOR_ME):
            continue
        if _prospect_matches_apps(p, apps):
            store.put_prospect(p.model_copy(update={"status": ProspectStatus.APPLIED}))
            flipped += 1
    return flipped


def _prospect_matches_apps(prospect: Prospect, apps: list[Application]) -> bool:
    comp = prospect.company_norm or normalise_company(prospect.company or "")
    if not comp:
        return False
    role = normalise_role(prospect.role)
    for app in apps:
        if app.company_norm != comp:
            continue
        if not role or not app.role:
            return True
        if token_set_ratio(role, normalise_role(app.role)) >= _ROLE_MATCH_THRESHOLD:
            return True
    return False
