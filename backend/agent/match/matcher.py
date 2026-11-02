"""Match a classified email to an existing application (or decide to create one).

Matching order (design.md "Matching order"):
  1. exact requisition_id
  2. same conversationId as an earlier event
  3. same normalised company AND role similarity >= 0.75 (token-set ratio)
  4. same normalised company where the user has exactly one non-closed application
  5. otherwise a new application (only for the email types in Requirement 4.2)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent.match.normalise import normalise_company, normalise_role, token_set_ratio
from domain.enums import CREATES_APPLICATION, EmailType, Status
from domain.models import Application, EmailFacts

ROLE_SIMILARITY_THRESHOLD = 0.75

# Statuses that count as "closed" for the single-open-application rule.
_CLOSED_STATUSES = frozenset(
    {Status.REJECTED, Status.CLOSED, Status.CLOSED_BY_EMPLOYER, Status.NO_RESPONSE}
)

# Email types that report the OUTCOME of an existing application (not a new one).
_OUTCOME_TYPES = frozenset(
    {
        EmailType.REJECTION,
        EmailType.OFFER,
        EmailType.ROLE_CLOSED,
        EmailType.ASSESSMENT_EXPIRED,
    }
)


class MatchMethod(StrEnum):
    REQUISITION_ID = "requisition_id"
    CONVERSATION_ID = "conversation_id"
    COMPANY_AND_ROLE = "company_and_role"
    SINGLE_OPEN_APP = "single_open_app"
    NEW = "new"
    NONE = "none"


@dataclass(frozen=True)
class MatchResult:
    """The outcome of matching one email.

    ``application`` is the matched existing application, or ``None`` when a new
    one should be created (``method == NEW``) or when nothing should happen
    (``method == NONE``: no match and the email type can't open an application).
    """

    method: MatchMethod
    application: Application | None


def match_email(
    facts: EmailFacts,
    conversation_id: str | None,
    applications: list[Application],
) -> MatchResult:
    """Match ``facts`` (one classified email) against the user's applications."""

    live = [a for a in applications if a.deleted_at is None]

    # 1. requisition id
    if facts.requisition_id:
        for app in live:
            if facts.requisition_id in app.requisition_ids:
                return MatchResult(MatchMethod.REQUISITION_ID, app)

    # 2. conversation id
    if conversation_id:
        for app in live:
            if conversation_id in app.conversation_ids:
                return MatchResult(MatchMethod.CONVERSATION_ID, app)

    company_norm = normalise_company(facts.company) if facts.company else ""

    # 3. same company + role similarity. Requires a role on both sides: an
    # empty-vs-empty comparison is not a role match (that is step 4's job).
    if company_norm:
        role_norm = normalise_role(facts.role)
        best: tuple[float, Application] | None = None
        for app in live:
            if app.company_norm != company_norm:
                continue
            app_role_norm = normalise_role(app.role)
            if not role_norm or not app_role_norm:
                continue
            score = token_set_ratio(role_norm, app_role_norm)
            if score >= ROLE_SIMILARITY_THRESHOLD and (best is None or score > best[0]):
                best = (score, app)
        if best is not None:
            return MatchResult(MatchMethod.COMPANY_AND_ROLE, best[1])

        here = [a for a in live if a.company_norm == company_norm]
        open_here = [a for a in here if a.status not in _CLOSED_STATUSES]

        # 3.5 the incoming email has no role to distinguish by. If there is
        # exactly one application at this company (open OR closed), it is almost
        # certainly a follow-up to it — match rather than create a duplicate.
        if not role_norm and len(here) == 1:
            return MatchResult(MatchMethod.SINGLE_OPEN_APP, here[0])

        # 3.6 an OUTCOME email (rejection / offer / role closed / assessment
        # expired) is the result of an application. If exactly one application is
        # open at this company, the outcome belongs to it — merge, even when the
        # role string differs, rather than spawning a duplicate closed row.
        # (The Squarepoint "shows twice" case: a roled rejection that didn't
        # fuzzy-match the open app's role still merges here.)
        if facts.email_type in _OUTCOME_TYPES and len(open_here) == 1:
            return MatchResult(MatchMethod.SINGLE_OPEN_APP, open_here[0])

        # 4. single OPEN application at this company (role present but unmatched)
        if len(open_here) == 1:
            return MatchResult(MatchMethod.SINGLE_OPEN_APP, open_here[0])

    # 5. create a new application, but only for the right email types
    if facts.email_type in CREATES_APPLICATION:
        return MatchResult(MatchMethod.NEW, None)

    return MatchResult(MatchMethod.NONE, None)
