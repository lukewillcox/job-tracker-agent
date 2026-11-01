"""Pydantic v2 models for every entity and every LLM output.

Timestamps are stored as timezone-aware UTC datetimes (see tech.md rules).
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from domain.enums import (
    DeadlineKind,
    EmailType,
    FirmType,
    FurthestStage,
    Priority,
    Programme,
    Status,
    TaskSource,
    UserStatus,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# --------------------------------------------------------------------------- #
# LLM output schema (classification)
# --------------------------------------------------------------------------- #
class EmailFacts(_Model):
    """Structured facts extracted from one email by the classifier.

    This is the tool-use / JSON schema the model must fill. It is validated on
    every classification; on repeated validation failure the email becomes
    ``Check email`` (Requirement 3.6).
    """

    is_job_application_email: bool
    email_type: EmailType
    company: str | None = None
    role: str | None = None
    programme: Programme = Programme.NOT_STATED
    requisition_id: str | None = None
    applied_via: str | None = None
    stage_reached: FurthestStage | None = None
    deadline: dt.datetime | None = None
    deadline_kind: DeadlineKind | None = None
    deadline_text: str | None = None
    interview_datetime: dt.datetime | None = None
    interview_location: str | None = None
    summary: str = Field(default="", max_length=140)
    confidence: float = Field(ge=0.0, le=1.0)


# --------------------------------------------------------------------------- #
# Stored entities
# --------------------------------------------------------------------------- #
class Note(_Model):
    """A dated note appended to an application timeline."""

    date: dt.date
    text: str


class Application(_Model):
    app_id: str
    company: str
    company_norm: str
    firm_type: FirmType = FirmType.UNCONFIRMED
    role: str | None = None
    programme: Programme = Programme.NOT_STATED
    applied_via: str | None = None
    date_applied: dt.date | None = None
    furthest_stage: FurthestStage | None = None
    status: Status = Status.AWAITING_RESPONSE
    last_update: dt.date | None = None
    next_step: str | None = None
    notes: list[Note] = Field(default_factory=list)
    requisition_ids: list[str] = Field(default_factory=list)
    conversation_ids: list[str] = Field(default_factory=list)
    # field name -> timestamp of the manual edit (UTC)
    manual_edits: dict[str, dt.datetime] = Field(default_factory=dict)
    deleted_at: dt.datetime | None = None


class Event(_Model):
    app_id: str
    email_type: EmailType
    summary: str
    email_date: dt.datetime
    web_link: str | None = None
    facts: EmailFacts
    prompt_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    message_id: str


class Deadline(_Model):
    deadline_id: str
    app_id: str
    what: str
    due_at: dt.datetime
    kind: DeadlineKind
    done_at: dt.datetime | None = None
    calendar_event_id: str | None = None
    # precomputed reminder schedule: remind_at -> sent_at (or None)
    reminders: dict[dt.datetime, dt.datetime | None] = Field(default_factory=dict)


class Task(_Model):
    """A Priorities-sheet row (auto-derived or manual)."""

    task_id: str
    priority: Priority
    text: str
    company: str | None = None
    due: dt.date | None = None  # None rendered as "ASAP"
    done_at: dt.datetime | None = None
    notes: str | None = None
    source: TaskSource = TaskSource.AUTO


class ScanRun(_Model):
    started_at: dt.datetime
    window_from: dt.datetime | None = None
    window_to: dt.datetime | None = None
    msgs_read: int = 0
    msgs_classified: int = 0
    new_apps: int = 0
    status_changes: int = 0
    errors: list[str] = Field(default_factory=list)
    duration_ms: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    est_cost: float = 0.0
    excel_status: str | None = None


class UserSettings(_Model):
    timezone: str = "Europe/London"
    backfill_months: int = Field(default=3, ge=1, le=12)
    calendar_sync: bool = False
    onedrive_export: bool = True
    role_focus: str | None = None
    practice_link: str | None = None
    scan_frequency: str = "every_2_days"  # daily | every_2_days | weekly | off
    reminder_hours_before: int = 48


class User(_Model):
    user_id: str
    email: str
    name: str | None = None
    ms_account_type: str | None = None
    scopes: list[str] = Field(default_factory=list)
    settings: UserSettings = Field(default_factory=UserSettings)
    delta_links: dict[str, str] = Field(default_factory=dict)
    last_export_at: dt.datetime | None = None
    onedrive_etag: str | None = None
    status: UserStatus = UserStatus.ACTIVE


class PrepPack(_Model):
    app_id: str
    content: dict[str, object]
    generated_at: dt.datetime
    model_id: str
    user_notes: str | None = None
