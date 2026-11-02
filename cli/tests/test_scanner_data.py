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
) -> IngestedMessage:
    return IngestedMessage(
        message_id="m1",
        internet_message_id="i1",
        conversation_id="c1",
        subject="subject",
        sender=sender,
        received=received,
        folder="inbox",
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
