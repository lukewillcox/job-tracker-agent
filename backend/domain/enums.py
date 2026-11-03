"""Enumerations from the requirements glossary.

Enum *values* are the human-readable strings shown in the UI and in Excel, so
exports need no mapping (see structure.md).
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """Application status shown to the user."""

    AWAITING_RESPONSE = "Awaiting response"
    ASSESSMENT_STAGE = "Assessment stage"
    INTERVIEW = "Interview"
    OFFER = "Offer"
    REJECTED = "Rejected"
    CLOSED = "Closed"
    CLOSED_BY_EMPLOYER = "Closed by employer"
    NO_RESPONSE = "No response"
    NOT_SUBMITTED = "Not submitted"
    CHECK_EMAIL = "Check email"


#: Statuses that count as "still active" (used by Summary + analytics).
ACTIVE_STATUSES: frozenset[Status] = frozenset(
    {Status.AWAITING_RESPONSE, Status.ASSESSMENT_STAGE, Status.INTERVIEW, Status.OFFER}
)


class FurthestStage(StrEnum):
    """Furthest point reached. Ordered; never moves backward.

    Order is defined by ``STAGE_ORDER`` below and exposed via :func:`stage_rank`.
    """

    STARTED = "Started"
    APPLIED = "Applied"
    ELIGIBILITY_CHECK_PASSED = "Eligibility check passed"
    ONLINE_ASSESSMENT = "Online assessment"
    VIDEO_INTERVIEW = "Video interview"
    INTERVIEW = "Interview"
    ASSESSMENT_CENTRE = "Assessment centre"
    FINAL_ROUND = "Final round"
    OFFER = "Offer"


#: Canonical ordering, weakest to furthest.
STAGE_ORDER: tuple[FurthestStage, ...] = (
    FurthestStage.STARTED,
    FurthestStage.APPLIED,
    FurthestStage.ELIGIBILITY_CHECK_PASSED,
    FurthestStage.ONLINE_ASSESSMENT,
    FurthestStage.VIDEO_INTERVIEW,
    FurthestStage.INTERVIEW,
    FurthestStage.ASSESSMENT_CENTRE,
    FurthestStage.FINAL_ROUND,
    FurthestStage.OFFER,
)

_STAGE_RANK: dict[FurthestStage, int] = {stage: i for i, stage in enumerate(STAGE_ORDER)}


def stage_rank(stage: FurthestStage) -> int:
    """Return the ordinal rank of a stage (higher means further)."""

    return _STAGE_RANK[stage]


def further_stage(a: FurthestStage | None, b: FurthestStage | None) -> FurthestStage | None:
    """Return whichever stage is further along, treating ``None`` as "no stage"."""

    if a is None:
        return b
    if b is None:
        return a
    return a if stage_rank(a) >= stage_rank(b) else b


class FirmType(StrEnum):
    """Firm type tag for an application."""

    INVESTMENT_BANK = "Investment bank"
    BOUTIQUE_INVESTMENT_BANK = "Boutique investment bank"
    HEDGE_FUND = "Hedge fund"
    TRADING_FIRM = "Trading firm"
    PRIVATE_EQUITY_CREDIT = "Private equity / credit"
    ASSET_MANAGER = "Asset manager"
    FINTECH = "Fintech"
    FINANCIAL_DATA = "Financial data"
    ENERGY_COMMODITIES = "Energy & commodities"
    PROFESSIONAL_SERVICES = "Professional services"
    CONSULTING = "Consulting"
    TECH = "Tech"
    OTHER = "Other"
    UNCONFIRMED = "Unconfirmed"


class Programme(StrEnum):
    """Programme type for a role."""

    GRADUATE = "Graduate"
    INTERNSHIP = "Internship"
    EXPERIENCED_HIRE = "Experienced hire"
    NOT_STATED = "Not stated"


class ProspectStatus(StrEnum):
    """Status of a prospect (a job found by the Prospects agent, not yet applied).

    Values are the human-readable strings shown in the Excel dropdown.
    """

    NEW = "New"
    INTERESTED = "Interested"
    APPLIED = "Applied"
    NOT_FOR_ME = "Not for me"


class EmailType(StrEnum):
    """Classification of a single email about an application.

    Mirrors the ``email_type`` field of the LLM output schema (design.md).
    """

    CONFIRMATION = "confirmation"
    ASSESSMENT_INVITE = "assessment_invite"
    INTERVIEW_INVITE = "interview_invite"
    REJECTION = "rejection"
    OFFER = "offer"
    ROLE_CLOSED = "role_closed"
    INCOMPLETE_APPLICATION_REMINDER = "incomplete_application_reminder"
    ASSESSMENT_COMPLETED = "assessment_completed"
    ASSESSMENT_EXPIRED = "assessment_expired"
    PROGRESS_UPDATE = "progress_update"
    OTHER = "other"


#: Email types that may create a brand-new application (Requirement 4.2).
CREATES_APPLICATION: frozenset[EmailType] = frozenset(
    {
        EmailType.CONFIRMATION,
        EmailType.ASSESSMENT_INVITE,
        EmailType.INTERVIEW_INVITE,
        EmailType.REJECTION,
        EmailType.OFFER,
        EmailType.ROLE_CLOSED,
    }
)


class DeadlineKind(StrEnum):
    EXPLICIT = "explicit"
    ESTIMATED = "estimated"


class Priority(StrEnum):
    URGENT = "1 - Urgent"
    HIGH = "2 - High"
    MEDIUM = "3 - Medium"
    LOW = "4 - Low"


class TaskSource(StrEnum):
    AUTO = "Auto"
    MANUAL = "Manual"


class UserStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    NEEDS_RECONNECT = "needs_reconnect"
