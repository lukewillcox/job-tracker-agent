"""Run one local scan: ingest -> classify (via host API) -> match -> Excel.

Reuses the backend's Graph delta ingest, prefilter, matcher, state machine and
Excel builder. Classification is delegated to the host's shared API. Email
bodies live in memory only; only extracted facts are stored locally.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from agent.ingest.delta import DEFAULT_FOLDERS, IngestedMessage, sync_folders
from agent.ingest.prefilter import PrefilterConfig
from agent.match.matcher import MatchMethod, match_email
from agent.match.state_machine import apply_event, apply_patch
from domain.enums import EmailType, FurthestStage, Status
from domain.firm_directory import default_directory, normalise
from domain.models import Application, EmailFacts, Event
from excel.builder import build_workbook
from integrations.graph_client import GraphClient

from jobtracker_cli.classify_client import ClassifyClient, ClassifyUsage
from jobtracker_cli.config import Config, get_refresh_token, set_refresh_token
from jobtracker_cli.localstore import LocalStore
from jobtracker_cli.ms_auth import access_token_from_refresh


@dataclass
class ScanSummary:
    read: int = 0
    passed: int = 0
    classified: int = 0
    capped: int = 0
    new_apps: int = 0
    status_changes: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


def run_scan(config: Config, invite_code: str, store: LocalStore) -> ScanSummary:
    refresh = get_refresh_token()
    if not refresh:
        raise RuntimeError("not signed in — run `jobtracker setup` first")

    access, rotated = access_token_from_refresh(refresh)
    if rotated:
        set_refresh_token(rotated)
    client = GraphClient(access)

    is_first = not config.delta_links
    backfill_start = (
        dt.datetime.now(dt.UTC) - dt.timedelta(days=30 * config.backfill_months)
        if is_first
        else None
    )
    ingest = sync_folders(
        client,
        folders=DEFAULT_FOLDERS,
        saved_delta_links=config.delta_links,
        backfill_start=backfill_start,
        prefilter_config=PrefilterConfig(),
        now=dt.datetime.now(dt.UTC),
    )
    config.delta_links.update(ingest.delta_links)

    summary = ScanSummary(read=ingest.read_count, passed=ingest.passed_count)

    # dedupe already-processed messages locally
    fresh = [m for m in ingest.messages if not store.is_processed(m.internet_message_id)]
    if not fresh:
        config.last_scan_at = dt.datetime.now(dt.UTC).isoformat()
        return summary

    classifier = ClassifyClient(config.api_url, invite_code, config.timezone)
    payload = [
        {
            "sender": m.sender,
            "subject": m.subject,
            "body_text": m.body_text,
            "received": m.received,
            "folder": m.folder,
        }
        for m in fresh
    ]
    results, usage = classifier.classify(payload)
    _apply_usage(summary, usage)

    apps = store.all_applications()
    for msg, res in zip(fresh, results, strict=True):
        if res.capped or res.facts is None:
            continue  # cap hit or no result; try again next scan (not marked processed)
        _apply_one(store, apps, msg, res.facts, summary)
        store.mark_processed(msg.internet_message_id)

    store.save()
    config.last_scan_at = dt.datetime.now(dt.UTC).isoformat()
    return summary


def _apply_one(
    store: LocalStore,
    apps: list[Application],
    msg: IngestedMessage,
    facts: EmailFacts,
    summary: ScanSummary,
) -> None:
    if not facts.is_job_application_email:
        return
    result = match_email(facts, msg.conversation_id, apps)
    if result.method == MatchMethod.NONE:
        return
    app = result.application
    if app is None:  # NEW
        app = _new_application(facts, msg)
        apps.append(app)
        summary.new_apps += 1

    evt = _build_event(app.app_id, facts, msg)
    patch = apply_event(app, evt)
    if not patch.timeline_only and (patch.status is not None or patch.furthest_stage is not None):
        summary.status_changes += 1
    updated = apply_patch(app, patch)
    _merge_ids(updated, facts, msg)
    store.put_application(updated)
    for i, a in enumerate(apps):
        if a.app_id == updated.app_id:
            apps[i] = updated
            break


def _new_application(facts: EmailFacts, msg: IngestedMessage) -> Application:
    company = facts.company or "Unknown"
    email_date = dt.datetime.fromisoformat(msg.received).date()
    app = Application(
        app_id=str(uuid.uuid4()),
        company=company,
        company_norm=normalise(company),
        role=facts.role,
        programme=facts.programme,
        applied_via=_applied_via(facts, msg),
        # Date applied = the confirmation's date. For other first-sighting email
        # types we don't know the apply date, so leave it unset.
        date_applied=email_date if facts.email_type == EmailType.CONFIRMATION else None,
        # Never leave a rejection/outcome row with a blank furthest stage: an
        # outcome implies they at least applied. Use the model's stage_reached
        # if given, else Applied.
        furthest_stage=facts.stage_reached or FurthestStage.APPLIED,
        status=Status.AWAITING_RESPONSE,
    )
    ft = default_directory().lookup(company)
    if ft is not None:
        app.firm_type = ft
    return app


# Map ATS sender domains -> clean platform label (strongest signal).
_ATS_DOMAIN_PLATFORM = {
    "myworkday.com": "Workday",
    "greenhouse-mail.io": "Greenhouse",
    "greenhouse.io": "Greenhouse",
    "ashbyhq.com": "Ashby",
    "hire.lever.co": "Lever",
    "lever.co": "Lever",
    "smartrecruiters.com": "SmartRecruiters",
    "tal.net": "Oracle Taleo",
    "jobs2web.com": "SuccessFactors",
    "icims.com": "iCIMS",
    "successfactors.com": "SuccessFactors",
    "avature.net": "Avature",
    "brassring.com": "BrassRing",
    "linkedin.com": "LinkedIn",
}
# Known ATS platform names the model might return (accept these as-is).
_KNOWN_PLATFORMS = {
    "workday", "greenhouse", "ashby", "lever", "smartrecruiters", "taleo",
    "oracle taleo", "successfactors", "icims", "avature", "brassring", "linkedin",
    "bright network", "dartmouth partners", "direct",
}
# Assessment providers that must NOT be used as "applied via".
_ASSESSMENT_PROVIDERS = {
    "shl", "hirevue", "pymetrics", "arctic shores", "codility", "hackerrank",
    "testgorilla", "arcticshores",
}


def _applied_via(facts: EmailFacts, msg: IngestedMessage) -> str:
    """Return the application PLATFORM, never a company or assessment provider.

    Priority: ATS sender domain -> a recognised platform name from the model ->
    'Direct'. The model sometimes returns the company or an assessment provider
    (SHL, Arctic Shores); those are rejected.
    """

    domain = msg.sender.rsplit("@", 1)[-1].lower() if "@" in msg.sender else ""
    for d, platform in _ATS_DOMAIN_PLATFORM.items():
        if domain.endswith(d):
            return platform

    raw = (facts.applied_via or "").strip()
    low = raw.lower()
    if low in _ASSESSMENT_PROVIDERS:
        return "Direct"
    if low in _KNOWN_PLATFORMS:
        # normalise capitalisation of known platforms
        return raw if raw[:1].isupper() else raw.title()
    # an unknown value that looks like the company name -> not a platform
    if facts.company and low == facts.company.strip().lower():
        return "Direct"
    return raw or "Direct"


def _build_event(app_id: str, facts: EmailFacts, msg: IngestedMessage) -> Event:
    return Event(
        app_id=app_id,
        email_type=facts.email_type,
        summary=facts.summary or facts.email_type.value,
        email_date=dt.datetime.fromisoformat(msg.received),
        web_link=msg.web_link,
        facts=facts,
        prompt_version="host",
        confidence=facts.confidence,
        message_id=msg.message_id,
    )


def _merge_ids(app: Application, facts: EmailFacts, msg: IngestedMessage) -> None:
    if facts.requisition_id and facts.requisition_id not in app.requisition_ids:
        app.requisition_ids.append(facts.requisition_id)
    if msg.conversation_id and msg.conversation_id not in app.conversation_ids:
        app.conversation_ids.append(msg.conversation_id)


def _apply_usage(summary: ScanSummary, usage: ClassifyUsage) -> None:
    summary.classified = usage.classified
    summary.capped = usage.capped
    summary.tokens_in = usage.tokens_in
    summary.tokens_out = usage.tokens_out


def write_excel(store: LocalStore) -> bytes:
    """Build the workbook from local data (written to OneDrive or saved locally)."""

    return build_workbook(store.applications())
