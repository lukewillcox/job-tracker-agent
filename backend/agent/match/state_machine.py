"""The application status state machine.

``apply_event`` is a pure function: given an application and a classified event,
it returns an :class:`AppPatch` describing the changes to make. It never mutates
its inputs, so it is trivially table-testable.

Rules (design.md "Status state machine"):

| Event type                      | New status                     | Furthest stage (forward only) |
|---------------------------------|--------------------------------|-------------------------------|
| confirmation                    | Awaiting response (if not fwd) | Applied                       |
| assessment_invite               | Assessment stage               | Online assessment             |
| assessment_completed            | (unchanged)                    | Online assessment; close d/l  |
| interview_invite                | Interview                      | stage_reached or Interview    |
| offer                           | Offer                          | Offer                         |
| rejection                       | Rejected                       | (unchanged)                   |
| role_closed                     | Closed by employer             | (unchanged)                   |
| incomplete_application_reminder | Not submitted (if new/already) | Started                       |
| assessment_expired              | Closed                         | (unchanged)                   |
| progress_update                 | from stage_reached             | from stage_reached            |

Extra rules:
- An event older than ``app.last_update`` adds to the timeline only (no field
  change). (Requirement 4.3 / 4.5 ordering)
- A field with a ``manual_edited_at`` newer than the event is not changed
  (Requirement 4.6).
- Furthest stage only ever moves forward (Requirement 4.4).
- A later "application reopened" style correction can undo a rejection; this is
  handled because a newer confirmation/progress_update event re-sets status
  while furthest stage (forward-only) is preserved (Optiver case).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from domain.enums import (
    EmailType,
    FurthestStage,
    Status,
    further_stage,
)
from domain.models import Application, Event, Note

# Fields that the state machine may set and that the user may have hand-edited.
_GUARDABLE_FIELDS = ("status", "furthest_stage", "next_step", "notes")


@dataclass
class AppPatch:
    """A set of changes to apply to an :class:`Application`.

    Attributes are ``None`` / empty when unchanged so callers (and tests) can
    see exactly what an event did. ``append_note`` is applied on top of existing
    notes. ``close_deadline`` signals that a matching open deadline should be
    marked done (assessment_completed).
    """

    status: Status | None = None
    furthest_stage: FurthestStage | None = None
    last_update: dt.date | None = None
    next_step: str | None = None
    append_note: Note | None = None
    close_deadline: bool = False
    # fields that were suppressed because of a newer manual edit
    skipped_manual: list[str] = field(default_factory=list)
    # True when the event was older than last_update (timeline-only)
    timeline_only: bool = False

    def is_empty(self) -> bool:
        return (
            self.status is None
            and self.furthest_stage is None
            and self.last_update is None
            and self.next_step is None
            and self.append_note is None
            and not self.close_deadline
        )


# status + furthest-stage target per event type; a value of ``None`` means
# "do not change". Furthest stage uses forward-only merge in apply_event.
_STATUS_BY_TYPE: dict[EmailType, Status | None] = {
    EmailType.CONFIRMATION: Status.AWAITING_RESPONSE,
    EmailType.ASSESSMENT_INVITE: Status.ASSESSMENT_STAGE,
    EmailType.ASSESSMENT_COMPLETED: None,
    EmailType.INTERVIEW_INVITE: Status.INTERVIEW,
    EmailType.OFFER: Status.OFFER,
    EmailType.REJECTION: Status.REJECTED,
    EmailType.ROLE_CLOSED: Status.CLOSED_BY_EMPLOYER,
    EmailType.INCOMPLETE_APPLICATION_REMINDER: Status.NOT_SUBMITTED,
    EmailType.ASSESSMENT_EXPIRED: Status.CLOSED,
    EmailType.PROGRESS_UPDATE: None,  # derived from stage_reached
    EmailType.OTHER: None,
}

_STAGE_BY_TYPE: dict[EmailType, FurthestStage | None] = {
    EmailType.CONFIRMATION: FurthestStage.APPLIED,
    EmailType.ASSESSMENT_INVITE: FurthestStage.ONLINE_ASSESSMENT,
    EmailType.ASSESSMENT_COMPLETED: FurthestStage.ONLINE_ASSESSMENT,
    EmailType.INTERVIEW_INVITE: FurthestStage.INTERVIEW,
    EmailType.OFFER: FurthestStage.OFFER,
    EmailType.REJECTION: None,
    EmailType.ROLE_CLOSED: None,
    EmailType.INCOMPLETE_APPLICATION_REMINDER: FurthestStage.STARTED,
    EmailType.ASSESSMENT_EXPIRED: None,
    EmailType.PROGRESS_UPDATE: None,  # derived from stage_reached
    EmailType.OTHER: None,
}


def _target_status(app: Application, event: Event) -> Status | None:
    et = event.email_type
    if et == EmailType.CONFIRMATION:
        # Only set Awaiting response if we're not already further along a live
        # pipeline; a confirmation shouldn't drag an Interview back.
        if app.status in (Status.INTERVIEW, Status.OFFER, Status.ASSESSMENT_STAGE):
            return None
        return Status.AWAITING_RESPONSE
    if et == EmailType.INCOMPLETE_APPLICATION_REMINDER:
        # Only when the app is new (Awaiting response default) or already so.
        if app.status in (Status.AWAITING_RESPONSE, Status.NOT_SUBMITTED):
            return Status.NOT_SUBMITTED
        return None
    if et == EmailType.PROGRESS_UPDATE:
        return _status_for_stage(event.facts.stage_reached)
    return _STATUS_BY_TYPE[et]


_INTERVIEW_STAGES = (
    FurthestStage.INTERVIEW,
    FurthestStage.ASSESSMENT_CENTRE,
    FurthestStage.FINAL_ROUND,
)


def _status_for_stage(stage: FurthestStage | None) -> Status | None:
    if stage is None:
        return None
    if stage in _INTERVIEW_STAGES:
        return Status.INTERVIEW
    if stage == FurthestStage.OFFER:
        return Status.OFFER
    if stage in (FurthestStage.ONLINE_ASSESSMENT, FurthestStage.VIDEO_INTERVIEW):
        return Status.ASSESSMENT_STAGE
    return None


def _target_stage(event: Event) -> FurthestStage | None:
    if event.email_type == EmailType.PROGRESS_UPDATE:
        return event.facts.stage_reached
    base = _STAGE_BY_TYPE[event.email_type]
    # interview_invite may carry a further stage_reached (e.g. Final round)
    if event.email_type == EmailType.INTERVIEW_INVITE:
        return further_stage(base, event.facts.stage_reached)
    return base


def apply_event(app: Application, event: Event) -> AppPatch:
    """Compute the changes an event makes to an application.

    Pure: ``app`` and ``event`` are not mutated.
    """

    patch = AppPatch()
    event_date = event.email_date.date()

    # Timeline-only when the event predates the last update.
    if app.last_update is not None and event_date < app.last_update:
        patch.timeline_only = True
        patch.append_note = _note(event)
        if event.email_type == EmailType.ASSESSMENT_COMPLETED:
            patch.close_deadline = True
        return patch

    target_status = _target_status(app, event)
    target_stage = _target_stage(event)

    # Manual-edit precedence: skip a field if the user edited it after the event.
    def edited_after(field_name: str) -> bool:
        ts = app.manual_edits.get(field_name)
        return ts is not None and ts.date() >= event_date

    if target_status is not None and target_status != app.status:
        if edited_after("status"):
            patch.skipped_manual.append("status")
        else:
            patch.status = target_status

    merged_stage = further_stage(app.furthest_stage, target_stage)
    if merged_stage is not None and merged_stage != app.furthest_stage:
        if edited_after("furthest_stage"):
            patch.skipped_manual.append("furthest_stage")
        else:
            patch.furthest_stage = merged_stage

    next_step = _next_step(event)
    if next_step is not None:
        if edited_after("next_step"):
            patch.skipped_manual.append("next_step")
        else:
            patch.next_step = next_step

    if event.email_type == EmailType.ASSESSMENT_COMPLETED:
        patch.close_deadline = True

    patch.append_note = _note(event)
    patch.last_update = event_date
    return patch


def _note(event: Event) -> Note:
    return Note(date=event.email_date.date(), text=event.summary)


def _next_step(event: Event) -> str | None:
    """Derive a human next step from the event, or None to leave unchanged."""

    facts = event.facts
    et = event.email_type
    if et in (EmailType.ASSESSMENT_INVITE, EmailType.INTERVIEW_INVITE):
        what = facts.deadline_text or (
            "assessment" if et == EmailType.ASSESSMENT_INVITE else "interview"
        )
        if facts.deadline is not None:
            return f"Complete {what} by {facts.deadline.strftime('%d/%m/%Y')}"
        if facts.interview_datetime is not None:
            return f"Attend {what} on {facts.interview_datetime.strftime('%d/%m/%Y')}"
        return f"Complete {what}"
    if et in (EmailType.REJECTION, EmailType.ROLE_CLOSED, EmailType.ASSESSMENT_EXPIRED):
        return "None"
    if et == EmailType.OFFER:
        return "Respond to offer"
    return None


def apply_patch(app: Application, patch: AppPatch) -> Application:
    """Return a copy of ``app`` with ``patch`` applied.

    Used by the matcher to turn a computed patch into the stored application,
    and by tests to assert the resulting state.
    """

    data = app.model_dump()
    if patch.status is not None:
        data["status"] = patch.status
    if patch.furthest_stage is not None:
        data["furthest_stage"] = patch.furthest_stage
    if patch.last_update is not None:
        data["last_update"] = patch.last_update
    if patch.next_step is not None:
        data["next_step"] = patch.next_step
    if patch.append_note is not None:
        data["notes"] = [*data["notes"], patch.append_note.model_dump()]
    return Application.model_validate(data)
