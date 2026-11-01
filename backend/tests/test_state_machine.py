import datetime as dt

import pytest

from agent.match.state_machine import apply_event, apply_patch
from domain.enums import EmailType, FurthestStage, Status
from domain.models import Application, EmailFacts, Event


def _app(**kwargs: object) -> Application:
    base: dict[str, object] = {
        "app_id": "app1",
        "company": "Example Bank",
        "company_norm": "example bank",
    }
    base.update(kwargs)
    return Application(**base)  # type: ignore[arg-type]


def _event(
    email_type: EmailType,
    *,
    date: dt.date,
    stage: FurthestStage | None = None,
    deadline: dt.datetime | None = None,
    deadline_text: str | None = None,
    confidence: float = 0.9,
) -> Event:
    facts = EmailFacts(
        is_job_application_email=True,
        email_type=email_type,
        stage_reached=stage,
        deadline=deadline,
        deadline_text=deadline_text,
        confidence=confidence,
    )
    return Event(
        app_id="app1",
        email_type=email_type,
        summary=f"{email_type.value}",
        email_date=dt.datetime.combine(date, dt.time(9, 0), tzinfo=dt.UTC),
        facts=facts,
        prompt_version="v1",
        confidence=confidence,
        message_id="m1",
    )


D = dt.date(2026, 10, 10)
# a neutral prior state (an app that only has a confirmation so far)
PRIOR = dt.date(2026, 9, 1)


@pytest.mark.parametrize(
    ("email_type", "expected_status", "expected_stage"),
    [
        (EmailType.CONFIRMATION, Status.AWAITING_RESPONSE, FurthestStage.APPLIED),
        (
            EmailType.ASSESSMENT_INVITE,
            Status.ASSESSMENT_STAGE,
            FurthestStage.ONLINE_ASSESSMENT,
        ),
        (EmailType.INTERVIEW_INVITE, Status.INTERVIEW, FurthestStage.INTERVIEW),
        (EmailType.OFFER, Status.OFFER, FurthestStage.OFFER),
        (EmailType.REJECTION, Status.REJECTED, FurthestStage.APPLIED),
        (EmailType.ROLE_CLOSED, Status.CLOSED_BY_EMPLOYER, FurthestStage.APPLIED),
        (EmailType.ASSESSMENT_EXPIRED, Status.CLOSED, FurthestStage.APPLIED),
    ],
)
def test_status_table(
    email_type: EmailType,
    expected_status: Status,
    expected_stage: FurthestStage | None,
) -> None:
    # start from a plain confirmed app so every transition is observable
    app = _app(
        status=Status.AWAITING_RESPONSE,
        furthest_stage=FurthestStage.APPLIED,
        last_update=PRIOR,
    )
    patch = apply_event(app, _event(email_type, date=D))
    result = apply_patch(app, patch)
    assert result.status == expected_status
    assert result.furthest_stage == expected_stage
    assert patch.last_update == D
    assert patch.append_note is not None


def test_incomplete_reminder_on_new_app_sets_not_submitted() -> None:
    app = _app(status=Status.AWAITING_RESPONSE)
    patch = apply_event(app, _event(EmailType.INCOMPLETE_APPLICATION_REMINDER, date=D))
    result = apply_patch(app, patch)
    assert result.status == Status.NOT_SUBMITTED
    assert result.furthest_stage == FurthestStage.STARTED


def test_furthest_stage_never_moves_backward() -> None:
    app = _app(
        furthest_stage=FurthestStage.INTERVIEW,
        status=Status.INTERVIEW,
        last_update=dt.date(2026, 10, 1),
    )
    # a confirmation arriving later should not drag the stage back to Applied
    patch = apply_event(app, _event(EmailType.CONFIRMATION, date=D))
    assert patch.furthest_stage is None  # unchanged (Interview already further)
    assert patch.status is None  # confirmation does not pull Interview back


def test_older_event_is_timeline_only() -> None:
    app = _app(status=Status.INTERVIEW, last_update=dt.date(2026, 10, 20))
    patch = apply_event(app, _event(EmailType.CONFIRMATION, date=dt.date(2026, 10, 1)))
    assert patch.timeline_only is True
    assert patch.status is None
    assert patch.furthest_stage is None
    assert patch.append_note is not None


def test_manual_edit_blocks_status_change() -> None:
    app = _app(
        status=Status.OFFER,
        last_update=dt.date(2026, 10, 1),
        manual_edits={"status": dt.datetime(2026, 10, 15, tzinfo=dt.UTC)},
    )
    # a rejection dated 2026-10-10, before the manual edit on the 15th
    patch = apply_event(app, _event(EmailType.REJECTION, date=D))
    assert patch.status is None
    assert "status" in patch.skipped_manual


def test_newer_email_overrides_manual_edit() -> None:
    app = _app(
        status=Status.OFFER,
        last_update=dt.date(2026, 10, 1),
        manual_edits={"status": dt.datetime(2026, 10, 5, tzinfo=dt.UTC)},
    )
    # a rejection dated 2026-10-10, after the manual edit on the 5th
    patch = apply_event(app, _event(EmailType.REJECTION, date=D))
    assert patch.status == Status.REJECTED


def test_optiver_reopen_undoes_rejection_but_keeps_stage() -> None:
    # Optiver case: rejection, then a correction reopening the application.
    app = _app(
        status=Status.REJECTED,
        furthest_stage=FurthestStage.APPLIED,
        last_update=dt.date(2026, 10, 1),
    )
    patch = apply_event(app, _event(EmailType.CONFIRMATION, date=D))
    result = apply_patch(app, patch)
    assert result.status == Status.AWAITING_RESPONSE  # reopened
    assert result.furthest_stage == FurthestStage.APPLIED  # preserved


def test_maven_rejection_keeps_furthest_stage_at_assessment() -> None:
    # Maven: progressed to assessment, then rejected. Stage stays at assessment.
    app = _app(
        status=Status.ASSESSMENT_STAGE,
        furthest_stage=FurthestStage.ONLINE_ASSESSMENT,
        last_update=dt.date(2026, 10, 1),
    )
    patch = apply_event(app, _event(EmailType.REJECTION, date=D))
    result = apply_patch(app, patch)
    assert result.status == Status.REJECTED
    assert result.furthest_stage == FurthestStage.ONLINE_ASSESSMENT  # unchanged


def test_deutsche_bank_expired_assessment_becomes_closed() -> None:
    app = _app(
        status=Status.ASSESSMENT_STAGE,
        furthest_stage=FurthestStage.ONLINE_ASSESSMENT,
        last_update=dt.date(2026, 10, 1),
    )
    patch = apply_event(app, _event(EmailType.ASSESSMENT_EXPIRED, date=D))
    assert patch.status == Status.CLOSED


def test_assessment_completed_closes_deadline_without_status_change() -> None:
    app = _app(
        status=Status.ASSESSMENT_STAGE,
        furthest_stage=FurthestStage.ONLINE_ASSESSMENT,
        last_update=dt.date(2026, 10, 1),
    )
    patch = apply_event(app, _event(EmailType.ASSESSMENT_COMPLETED, date=D))
    assert patch.status is None
    assert patch.close_deadline is True


def test_assessment_invite_sets_next_step_with_deadline() -> None:
    deadline = dt.datetime(2026, 11, 2, 23, 59, tzinfo=dt.UTC)
    patch = apply_event(
        _app(),
        _event(
            EmailType.ASSESSMENT_INVITE,
            date=D,
            deadline=deadline,
            deadline_text="SHL online assessment",
        ),
    )
    assert patch.next_step == "Complete SHL online assessment by 02/11/2026"


def test_apply_event_does_not_mutate_inputs() -> None:
    app = _app(status=Status.AWAITING_RESPONSE)
    original_status = app.status
    apply_event(app, _event(EmailType.REJECTION, date=D))
    assert app.status == original_status
