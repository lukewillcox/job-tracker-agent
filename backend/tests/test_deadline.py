import datetime as dt

from agent.classify.deadline import resolve_relative_deadline

LONDON = "Europe/London"
# a fixed email received time: Tue 2026-10-06 09:00 UTC
RECEIVED = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def test_within_five_days() -> None:
    due = resolve_relative_deadline("Please complete within 5 days of this email", RECEIVED, LONDON)
    assert due is not None
    # 5 days after the 6th = the 11th, end of local day -> 22:59 UTC (BST)
    assert due.date() == dt.date(2026, 10, 11)


def test_within_five_days_word_form() -> None:
    due = resolve_relative_deadline("complete within five business days", RECEIVED, LONDON)
    assert due is not None
    assert due.date() == dt.date(2026, 10, 11)


def test_within_hours() -> None:
    due = resolve_relative_deadline("respond within 48 hours", RECEIVED, LONDON)
    assert due is not None
    assert due == RECEIVED + dt.timedelta(hours=48)


def test_by_midnight_weekday() -> None:
    # email on Tue 06/10; "by midnight Monday" -> next Monday 12/10
    due = resolve_relative_deadline("submit by midnight Monday", RECEIVED, LONDON)
    assert due is not None
    assert due.date() == dt.date(2026, 10, 12)


def test_by_weekday_same_week() -> None:
    # Tue 06/10; "by Friday" -> Fri 09/10
    due = resolve_relative_deadline("assessment due by Friday", RECEIVED, LONDON)
    assert due is not None
    assert due.date() == dt.date(2026, 10, 9)


def test_unparseable_returns_none() -> None:
    assert resolve_relative_deadline("please apply soon", RECEIVED, LONDON) is None


def test_naive_datetime_raises() -> None:
    import pytest

    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_relative_deadline("within 3 days", dt.datetime(2026, 10, 6, 9, 0), LONDON)


def test_result_is_utc() -> None:
    due = resolve_relative_deadline("within 2 days", RECEIVED, LONDON)
    assert due is not None
    assert due.tzinfo == dt.UTC
