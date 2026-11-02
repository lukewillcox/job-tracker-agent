"""Match-and-apply Lambda (Step Functions step).

Input event shape (from the classify Map step):

    {"user_id": "...", "classified": [{"facts": {...EmailFacts...},
                                        "conversation_id": "...",
                                        "web_link": "...",
                                        "message_id": "...",
                                        "internet_message_id": "..."}]}

For each classified email that is a job application, it matches to an existing
application (or creates one), applies the status state machine, writes the
updated application, appends a timeline event, and records the processed message.
Returns counts for the scan report.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from agent.match.matcher import MatchMethod, match_email
from agent.match.state_machine import apply_event, apply_patch
from domain.enums import Status
from domain.firm_directory import default_directory, normalise
from domain.models import Application, EmailFacts, Event
from store.client import get_repository
from store.repository import Repository

_PROCESSED_TTL_DAYS = 400


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    user_id = event["user_id"]
    classified = event.get("classified", [])
    repo = get_repository()
    result = apply_classified(repo, user_id, classified)

    # persist a ScanRun record for history/analytics (Requirement 7.4)
    _record_scan_run(repo, user_id, event, result, classified)

    return result


def _record_scan_run(
    repo: Repository,
    user_id: str,
    event: dict[str, Any],
    result: dict[str, Any],
    classified: list[dict[str, Any]],
) -> None:
    from domain.models import ScanRun

    tokens_in = sum(int(c.get("input_tokens", 0)) for c in classified)
    tokens_out = sum(int(c.get("output_tokens", 0)) for c in classified)
    repo.put_scan(
        user_id,
        ScanRun(
            started_at=dt.datetime.now(dt.UTC),
            msgs_read=int(event.get("read_count", 0)),
            msgs_classified=len(classified),
            new_apps=result["new_apps"],
            status_changes=result["status_changes"],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        ),
    )


def apply_classified(
    repo: Repository, user_id: str, classified: list[dict[str, Any]]
) -> dict[str, Any]:
    apps = repo.list_applications(user_id)
    new_apps = 0
    status_changes = 0

    for item in classified:
        facts = EmailFacts.model_validate(item["facts"])
        if not facts.is_job_application_email:
            _record_processed(repo, user_id, item, "not_job")
            continue

        result = match_email(facts, item.get("conversation_id"), apps)
        if result.method == MatchMethod.NONE:
            _record_processed(repo, user_id, item, "check")
            continue

        app = result.application
        if app is None:  # MatchMethod.NEW
            app = _new_application(facts)
            apps.append(app)
            new_apps += 1

        evt = _build_event(app.app_id, facts, item)
        patch = apply_event(app, evt)

        if not patch.timeline_only and (
            patch.status is not None or patch.furthest_stage is not None
        ):
            status_changes += 1

        updated = apply_patch(app, evt_patch := patch)
        _merge_identifiers(updated, facts, item)
        repo.put_application(user_id, updated)
        repo.put_event(user_id, evt)
        _replace_in_list(apps, updated)
        _record_processed(repo, user_id, item, "job")
        _ = evt_patch  # patch retained for clarity/debugging

    return {"user_id": user_id, "new_apps": new_apps, "status_changes": status_changes}


def _new_application(facts: EmailFacts) -> Application:
    company = facts.company or "Unknown"
    company_norm = normalise(company)
    firm_type = default_directory().lookup(company)
    app = Application(
        app_id=str(uuid.uuid4()),
        company=company,
        company_norm=company_norm,
        role=facts.role,
        programme=facts.programme,
        applied_via=facts.applied_via,
        status=Status.AWAITING_RESPONSE,
    )
    if firm_type is not None:
        app.firm_type = firm_type
    return app


def _build_event(app_id: str, facts: EmailFacts, item: dict[str, Any]) -> Event:
    email_date = dt.datetime.fromisoformat(item["email_date"])
    return Event(
        app_id=app_id,
        email_type=facts.email_type,
        summary=facts.summary or facts.email_type.value,
        email_date=email_date,
        web_link=item.get("web_link"),
        facts=facts,
        prompt_version=item.get("prompt_version", "v1"),
        confidence=facts.confidence,
        message_id=item["message_id"],
    )


def _merge_identifiers(app: Application, facts: EmailFacts, item: dict[str, Any]) -> None:
    if facts.requisition_id and facts.requisition_id not in app.requisition_ids:
        app.requisition_ids.append(facts.requisition_id)
    conv = item.get("conversation_id")
    if conv and conv not in app.conversation_ids:
        app.conversation_ids.append(conv)


def _replace_in_list(apps: list[Application], updated: Application) -> None:
    for i, a in enumerate(apps):
        if a.app_id == updated.app_id:
            apps[i] = updated
            return
    apps.append(updated)


def _record_processed(
    repo: Repository, user_id: str, item: dict[str, Any], outcome: str
) -> None:
    imid = item.get("internet_message_id")
    if not imid:
        return
    ttl = int((dt.datetime.now(dt.UTC) + dt.timedelta(days=_PROCESSED_TTL_DAYS)).timestamp())
    repo.mark_processed(user_id, imid, outcome, ttl)
