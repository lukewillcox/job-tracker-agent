"""Resolve relative deadlines from email text to an absolute time.

The classifier returns an absolute ``deadline`` when the email states one. When
it only states a relative deadline ("within five days of this email", "by
midnight Monday"), the model returns ``deadline=None`` and the relative phrase
in ``deadline_text``; this module resolves it from the email's received time and
the user's time zone (Requirement 8.1-8.2).

Resolution is deliberately conservative: anything it can't parse returns
``None`` so the caller keeps the explicit model value or leaves the deadline
unset rather than inventing a date.
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

__all__ = ["resolve_relative_deadline"]

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "fourteen": 14,
    "a": 1,
    "an": 1,
}

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

# "within 5 days" / "within five business days" / "in 3 days"
_WITHIN_DAYS_RE = re.compile(
    r"\b(?:within|in)\s+(\d+|" + "|".join(_NUMBER_WORDS) + r")\s+(?:business\s+|working\s+)?days?\b"
)
_WITHIN_HOURS_RE = re.compile(
    r"\b(?:within|in)\s+(\d+|" + "|".join(_NUMBER_WORDS) + r")\s+hours?\b"
)
# "by midnight Monday" / "by Friday" / "by end of day Wednesday"
_BY_WEEKDAY_RE = re.compile(
    r"\bby\s+(?:midnight\s+|end\s+of\s+(?:day|business)\s+)?("
    + "|".join(_WEEKDAYS)
    + r")\b"
)
_MIDNIGHT_RE = re.compile(r"\bmidnight\b")
_END_OF_DAY_RE = re.compile(r"\bend\s+of\s+(?:day|business)\b|\beod\b|\bcob\b")


def _to_int(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def resolve_relative_deadline(
    text: str,
    email_received: dt.datetime,
    timezone: str,
) -> dt.datetime | None:
    """Resolve a relative deadline phrase to an absolute UTC datetime.

    ``email_received`` must be timezone-aware. The returned value is also
    timezone-aware (UTC). Returns ``None`` when no supported phrase is found.
    """

    if email_received.tzinfo is None:
        raise ValueError("email_received must be timezone-aware")

    tz = ZoneInfo(timezone)
    local = email_received.astimezone(tz)
    phrase = text.lower()

    # "within N hours" -> received + N hours
    m = _WITHIN_HOURS_RE.search(phrase)
    if m:
        due = local + dt.timedelta(hours=_to_int(m.group(1)))
        return due.astimezone(dt.UTC)

    # "within N days" -> end of the Nth day after the email
    m = _WITHIN_DAYS_RE.search(phrase)
    if m:
        due_day = (local + dt.timedelta(days=_to_int(m.group(1)))).date()
        return _end_of_day(due_day, tz)

    # "by <weekday>" -> the next occurrence of that weekday (today counts)
    m = _BY_WEEKDAY_RE.search(phrase)
    if m:
        target = _WEEKDAYS[m.group(1)]
        ahead = (target - local.weekday()) % 7
        due_day = (local + dt.timedelta(days=ahead)).date()
        if _MIDNIGHT_RE.search(phrase):
            # "midnight Monday" = end of Monday (23:59 local)
            return _end_of_day(due_day, tz)
        return _end_of_day(due_day, tz)

    # bare "end of day" / "by midnight" with no weekday -> today
    if _MIDNIGHT_RE.search(phrase) or _END_OF_DAY_RE.search(phrase):
        return _end_of_day(local.date(), tz)

    return None


def _end_of_day(day: dt.date, tz: ZoneInfo) -> dt.datetime:
    """23:59 local on ``day``, as UTC."""

    local = dt.datetime.combine(day, dt.time(23, 59), tzinfo=tz)
    return local.astimezone(dt.UTC)
