"""Data-quality tests for the CLI scanner's application construction."""

from __future__ import annotations

import datetime as dt

from agent.ingest.delta import IngestedMessage
from domain.enums import EmailType, FurthestStage, Programme
from domain.models import EmailFacts

from jobtracker_cli.scanner import _applied_via, _new_application


def _msg(
    sender: str = "no-reply@myworkday.com",
    received: str = "2026-10-05T09:00:00+00:00",
    folder: str = "inbox",
) -> IngestedMessage:
    return IngestedMessage(
        message_id="m1",
        internet_message_id="i1",
        conversation_id="c1",
        subject="subject",
        sender=sender,
        received=received,
        folder=folder,
        web_link="https://outlook/x",
        body_text="body",
    )


def _facts(**kw: object) -> EmailFacts:
    base: dict[str, object] = {
        "is_job_application_email": True,
        "email_type": EmailType.CONFIRMATION,
        "company": "Example Bank",
        "confidence": 0.95,
    }
    base.update(kw)
    return EmailFacts(**base)  # type: ignore[arg-type]


# --- Fix 1: Date applied from the confirmation date ----------------------
def test_confirmation_sets_date_applied_from_email() -> None:
    msg = _msg(received="2026-10-05T09:00:00+00:00")
    app = _new_application(_facts(email_type=EmailType.CONFIRMATION), msg)
    assert app.date_applied == dt.date(2026, 10, 5)


def test_non_confirmation_leaves_date_applied_unset() -> None:
    # a rejection as first sighting: we don't know the apply date
    app = _new_application(_facts(email_type=EmailType.REJECTION), _msg())
    assert app.date_applied is None


# --- Fix 4: furthest stage never blank, even on a rejection --------------
def test_rejection_new_app_keeps_furthest_stage_not_blank() -> None:
    app = _new_application(_facts(email_type=EmailType.REJECTION, stage_reached=None), _msg())
    assert app.furthest_stage == FurthestStage.APPLIED  # never None


def test_new_app_uses_model_stage_when_given() -> None:
    app = _new_application(
        _facts(email_type=EmailType.REJECTION, stage_reached=FurthestStage.ONLINE_ASSESSMENT),
        _msg(),
    )
    assert app.furthest_stage == FurthestStage.ONLINE_ASSESSMENT


# --- Fix 2: Applied via is the platform, not company/assessment provider -
def test_applied_via_from_ats_domain() -> None:
    assert _applied_via(_facts(), _msg(sender="x@myworkday.com")) == "Workday"
    assert _applied_via(_facts(), _msg(sender="x@greenhouse-mail.io")) == "Greenhouse"
    assert _applied_via(_facts(), _msg(sender="x@hire.lever.co")) == "Lever"


def test_applied_via_rejects_assessment_provider() -> None:
    # model returned "Arctic Shores" (an assessment tool) -> must be Direct
    f = _facts(applied_via="Arctic Shores")
    assert _applied_via(f, _msg(sender="x@unknownfirm.com")) == "Direct"


def test_applied_via_rejects_company_name() -> None:
    f = _facts(company="Example Bank", applied_via="Example Bank")
    assert _applied_via(f, _msg(sender="x@unknownfirm.com")) == "Direct"


def test_applied_via_accepts_known_platform_name() -> None:
    f = _facts(applied_via="LinkedIn")
    assert _applied_via(f, _msg(sender="x@unknownfirm.com")) == "LinkedIn"


def test_applied_via_defaults_direct_when_unknown() -> None:
    f = _facts(applied_via=None)
    assert _applied_via(f, _msg(sender="x@unknownfirm.com")) == "Direct"


def test_programme_passthrough() -> None:
    app = _new_application(_facts(programme=Programme.INTERNSHIP), _msg())
    assert app.programme == Programme.INTERNSHIP


def test_applied_via_blocks_newly_added_assessment_providers() -> None:
    for provider in ("CodeSignal", "Criteria Corp", "Plum"):
        f = _facts(applied_via=provider)
        assert _applied_via(f, _msg(sender="x@unknownfirm.com")) == "Direct"


# --- Fix 3: chronological processing merges the later rejection -----------
def test_rejection_after_confirmation_merges_to_one_app() -> None:
    from jobtracker_cli.scanner import ScanSummary, _apply_one

    apps: list = []
    summary = ScanSummary()
    conf = _facts(
        email_type=EmailType.CONFIRMATION, company="Squarepoint", role="Desk Quant Analyst"
    )
    rej = _facts(email_type=EmailType.REJECTION, company="Squarepoint", role=None)

    # applied in chronological order (confirmation first, then rejection)
    _apply_one(_store_stub(apps), apps, _msg(received="2026-10-26T09:00:00+00:00"), conf, summary)
    _apply_one(_store_stub(apps), apps, _msg(received="2026-10-27T09:00:00+00:00"), rej, summary)

    live = [a for a in apps if a.deleted_at is None]
    assert len(live) == 1  # merged, not duplicated
    assert live[0].status.value == "Rejected"
    assert live[0].role == "Desk Quant Analyst"  # kept the roled confirmation's role


class _StoreStub:
    """Minimal LocalStore stand-in for _apply_one."""

    def __init__(self, apps: list) -> None:
        self._apps = apps
        self.deadlines: list = []

    def put_application(self, app: object) -> None:
        pass

    def put_deadline(self, deadline: object) -> None:
        self.deadlines.append(deadline)


def _store_stub(apps: list) -> object:
    return _StoreStub(apps)


# --- Fix 2: Deadline recorded whenever an email gives a due date ----------
def test_due_date_records_a_deadline() -> None:
    from jobtracker_cli.scanner import ScanSummary, _apply_one

    apps: list = []
    store = _StoreStub(apps)
    due = dt.datetime(2026, 11, 2, 23, 59, tzinfo=dt.UTC)
    facts = _facts(
        email_type=EmailType.ASSESSMENT_INVITE,
        company="Barclays",
        deadline=due,
        deadline_text="SHL assessment",
    )
    _apply_one(store, apps, _msg(received="2026-10-28T09:00:00+00:00"), facts, ScanSummary())
    assert len(store.deadlines) == 1
    assert store.deadlines[0].due_at.date() == dt.date(2026, 11, 2)
    assert store.deadlines[0].what == "SHL assessment"


def test_no_due_date_records_no_deadline() -> None:
    from jobtracker_cli.scanner import ScanSummary, _apply_one

    apps: list = []
    store = _StoreStub(apps)
    facts = _facts(email_type=EmailType.CONFIRMATION, company="Citi", deadline=None)
    _apply_one(store, apps, _msg(), facts, ScanSummary())
    assert store.deadlines == []


# --- Fix 3: don't note the user's own sent mail unless it's an application -
def test_sent_reply_is_ignored() -> None:
    from jobtracker_cli.scanner import ScanSummary, _apply_one

    apps: list = []
    store = _StoreStub(apps)
    # a 'thank you' reply in Sent Items classified as progress_update
    facts = _facts(email_type=EmailType.PROGRESS_UPDATE, company="Citi")
    msg = _msg(sender="luke@outlook.com", folder="sentitems")
    _apply_one(store, apps, msg, facts, ScanSummary())
    assert len(apps) == 0  # no row created from a sent reply


def test_sent_cv_confirmation_still_counts() -> None:
    from jobtracker_cli.scanner import ScanSummary, _apply_one

    apps: list = []
    store = _StoreStub(apps)
    # a CV emailed to a recruiter -> confirmation, from Sent Items -> counts
    facts = _facts(email_type=EmailType.CONFIRMATION, company="Taula Capital")
    msg = _msg(sender="luke@outlook.com", folder="sentitems")
    _apply_one(store, apps, msg, facts, ScanSummary())
    assert len(apps) == 1
    assert apps[0].company == "Taula Capital"
