import datetime as dt

from api.analytics import (
    firm_type_breakdown,
    funnel,
    gone_quiet_share,
    summary_counts,
)
from domain.enums import FirmType, FurthestStage, Programme, Status
from domain.models import Application


def _app(
    app_id: str,
    firm_type: FirmType,
    status: Status,
    stage: FurthestStage | None,
    programme: Programme = Programme.GRADUATE,
    **kw: object,
) -> Application:
    return Application(
        app_id=app_id,
        company=app_id,
        company_norm=app_id,
        firm_type=firm_type,
        status=status,
        furthest_stage=stage,
        programme=programme,
        **kw,  # type: ignore[arg-type]
    )


def _portfolio() -> list[Application]:
    return [
        _app("a", FirmType.INVESTMENT_BANK, Status.AWAITING_RESPONSE, FurthestStage.APPLIED),
        _app(
            "b",
            FirmType.INVESTMENT_BANK,
            Status.ASSESSMENT_STAGE,
            FurthestStage.ONLINE_ASSESSMENT,
        ),
        _app("c", FirmType.HEDGE_FUND, Status.INTERVIEW, FurthestStage.INTERVIEW),
        _app("d", FirmType.HEDGE_FUND, Status.REJECTED, FurthestStage.ONLINE_ASSESSMENT),
        _app("e", FirmType.TRADING_FIRM, Status.OFFER, FurthestStage.OFFER),
    ]


def test_summary_totals() -> None:
    s = summary_counts(_portfolio())
    assert s.total == 5
    assert s.still_active == 4  # awaiting, assessment, interview, offer
    assert s.rejected_or_closed == 1
    assert s.by_status[Status.OFFER] == 1


def test_summary_excludes_deleted() -> None:
    apps = _portfolio()
    apps[0].deleted_at = dt.datetime.now(dt.UTC)
    s = summary_counts(apps)
    assert s.total == 4


def test_firm_type_breakdown_got_past_application() -> None:
    rows = {r.firm_type: r for r in firm_type_breakdown(_portfolio())}
    ib = rows[FirmType.INVESTMENT_BANK]
    assert ib.applications == 2
    assert ib.still_active == 2
    # 'b' reached Online assessment (past Applied); 'a' only Applied
    assert ib.got_past_application == 1
    hf = rows[FirmType.HEDGE_FUND]
    assert hf.rejected_or_closed == 1
    assert hf.got_past_application == 2  # both reached assessment/interview


def test_funnel_counts_reached_or_beyond() -> None:
    f = funnel(_portfolio())
    assert f.applied == 5  # all reached at least Applied
    assert f.assessment == 4  # b, c, d, e
    assert f.interview == 2  # c, e
    assert f.offer == 1  # e


def test_funnel_conversion_guards_zero() -> None:
    f = funnel([])
    assert f.conversion()["applied_to_assessment"] == 0.0


def test_gone_quiet_share() -> None:
    today = dt.date(2026, 11, 1)
    apps = [
        _app("x", FirmType.INVESTMENT_BANK, Status.AWAITING_RESPONSE, FurthestStage.APPLIED,
             last_update=dt.date(2026, 10, 1)),  # 31 days -> quiet
        _app("y", FirmType.INVESTMENT_BANK, Status.AWAITING_RESPONSE, FurthestStage.APPLIED,
             last_update=dt.date(2026, 10, 28)),  # 4 days -> active
    ]
    assert gone_quiet_share(apps, today=today) == 0.5


def test_summary_matches_excel_countif_logic() -> None:
    # The Excel Summary uses COUNTIF on the Status column; our summary_counts
    # must agree. Reproduce the COUNTIF per status and compare.
    apps = _portfolio()
    s = summary_counts(apps)
    for status in Status:
        countif = sum(1 for a in apps if a.deleted_at is None and a.status == status)
        assert s.by_status[status] == countif
