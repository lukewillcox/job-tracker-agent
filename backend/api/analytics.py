"""Analytics computed from a user's applications.

``summary_counts`` is the single source of truth shared by the web dashboard
and the Excel Summary sheet, so the numbers always agree (Requirement 11.5).
Everything here is a pure function over a list of applications; it does no I/O.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from domain.enums import (
    ACTIVE_STATUSES,
    FirmType,
    FurthestStage,
    Programme,
    Status,
    stage_rank,
)
from domain.models import Application

__all__ = [
    "FirmTypeBreakdown",
    "Funnel",
    "SummaryCounts",
    "firm_type_breakdown",
    "funnel",
    "gone_quiet_share",
    "summary_counts",
]

# Statuses that count as rejected/closed in the Summary.
_REJECTED_OR_CLOSED = frozenset({Status.REJECTED, Status.CLOSED, Status.CLOSED_BY_EMPLOYER})

# "Got past application": furthest stage strictly beyond Applied.
_BEYOND_APPLIED_MIN_RANK = stage_rank(FurthestStage.ELIGIBILITY_CHECK_PASSED)

# gone-quiet threshold in days (Requirement 4.7).
GONE_QUIET_DAYS = 21


def _live(apps: list[Application]) -> list[Application]:
    return [a for a in apps if a.deleted_at is None]


def _got_past_application(app: Application) -> bool:
    if app.furthest_stage is None:
        return False
    return stage_rank(app.furthest_stage) >= _BEYOND_APPLIED_MIN_RANK


@dataclass
class SummaryCounts:
    total: int = 0
    by_status: dict[Status, int] = field(default_factory=dict)
    still_active: int = 0
    rejected_or_closed: int = 0
    by_programme: dict[Programme, int] = field(default_factory=dict)


def summary_counts(apps: list[Application]) -> SummaryCounts:
    """Headline counts, matching the Excel Summary 'By status' block."""

    live = _live(apps)
    by_status: dict[Status, int] = {s: 0 for s in Status}
    by_programme: dict[Programme, int] = {p: 0 for p in Programme}
    still_active = 0
    rejected_or_closed = 0

    for app in live:
        by_status[app.status] += 1
        by_programme[app.programme] += 1
        if app.status in ACTIVE_STATUSES:
            still_active += 1
        if app.status in _REJECTED_OR_CLOSED:
            rejected_or_closed += 1

    return SummaryCounts(
        total=len(live),
        by_status=by_status,
        still_active=still_active,
        rejected_or_closed=rejected_or_closed,
        by_programme=by_programme,
    )


@dataclass
class FirmTypeBreakdown:
    firm_type: FirmType
    applications: int = 0
    still_active: int = 0
    rejected_or_closed: int = 0
    got_past_application: int = 0


def firm_type_breakdown(apps: list[Application]) -> list[FirmTypeBreakdown]:
    """Per-firm-type breakdown, matching the Excel Summary 'By firm type' block."""

    rows: dict[FirmType, FirmTypeBreakdown] = {
        ft: FirmTypeBreakdown(firm_type=ft) for ft in FirmType
    }
    for app in _live(apps):
        row = rows[app.firm_type]
        row.applications += 1
        if app.status in ACTIVE_STATUSES:
            row.still_active += 1
        if app.status in _REJECTED_OR_CLOSED:
            row.rejected_or_closed += 1
        if _got_past_application(app):
            row.got_past_application += 1
    return [rows[ft] for ft in FirmType]


@dataclass
class Funnel:
    """Funnel by furthest stage: each step counts apps that reached it or beyond."""

    applied: int = 0
    assessment: int = 0
    interview: int = 0
    final: int = 0
    offer: int = 0

    def conversion(self) -> dict[str, float]:
        """Step-to-step conversion rates (0..1), guarding against zero."""

        def ratio(numer: int, denom: int) -> float:
            return numer / denom if denom else 0.0

        return {
            "applied_to_assessment": ratio(self.assessment, self.applied),
            "assessment_to_interview": ratio(self.interview, self.assessment),
            "interview_to_final": ratio(self.final, self.interview),
            "final_to_offer": ratio(self.offer, self.final),
        }


def funnel(apps: list[Application]) -> Funnel:
    """Count applications that reached at least each stage (Requirement 11.1)."""

    f = Funnel()
    thresholds = {
        "applied": stage_rank(FurthestStage.APPLIED),
        "assessment": stage_rank(FurthestStage.ONLINE_ASSESSMENT),
        "interview": stage_rank(FurthestStage.INTERVIEW),
        "final": stage_rank(FurthestStage.FINAL_ROUND),
        "offer": stage_rank(FurthestStage.OFFER),
    }
    for app in _live(apps):
        if app.furthest_stage is None:
            continue
        r = stage_rank(app.furthest_stage)
        if r >= thresholds["applied"]:
            f.applied += 1
        if r >= thresholds["assessment"]:
            f.assessment += 1
        if r >= thresholds["interview"]:
            f.interview += 1
        if r >= thresholds["final"]:
            f.final += 1
        if r >= thresholds["offer"]:
            f.offer += 1
    return f


def gone_quiet_share(apps: list[Application], today: dt.date | None = None) -> float:
    """Share (0..1) of active applications with no update for >= 21 days."""

    now = today or dt.date.today()
    quiet_eligible = (Status.AWAITING_RESPONSE, Status.ASSESSMENT_STAGE)
    active = [a for a in _live(apps) if a.status in quiet_eligible]
    if not active:
        return 0.0
    quiet = sum(
        1
        for a in active
        if a.last_update is not None and (now - a.last_update).days >= GONE_QUIET_DAYS
    )
    return quiet / len(active)


def applications_per_week(apps: list[Application]) -> dict[str, int]:
    """ISO-week -> count of applications by date_applied (Requirement 11.4)."""

    weeks: dict[str, int] = defaultdict(int)
    for app in _live(apps):
        if app.date_applied is None:
            continue
        iso = app.date_applied.isocalendar()
        weeks[f"{iso.year}-W{iso.week:02d}"] += 1
    return dict(sorted(weeks.items()))
