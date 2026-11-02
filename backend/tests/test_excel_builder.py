import datetime as dt
import io

from openpyxl import load_workbook

from domain.enums import FirmType, FurthestStage, Priority, Programme, Status, TaskSource
from domain.models import Application, Note, ScanRun, Task
from excel.builder import APP_HEADERS, build_workbook


def _apps() -> list[Application]:
    return [
        Application(
            app_id="a1",
            company="Example Bank",
            company_norm="example bank",
            firm_type=FirmType.INVESTMENT_BANK,
            role="2027 Markets Graduate Analyst",
            programme=Programme.GRADUATE,
            applied_via="Workday",
            date_applied=dt.date(2026, 10, 5),
            furthest_stage=FurthestStage.ONLINE_ASSESSMENT,
            status=Status.ASSESSMENT_STAGE,
            last_update=dt.date(2026, 10, 9),
            next_step="Complete SHL assessment by 14/10/2026",
            notes=[Note(date=dt.date(2026, 10, 9), text="invited to SHL online assessment")],
        ),
        Application(
            app_id="a2",
            company="Example Capital",
            company_norm="example capital",
            firm_type=FirmType.HEDGE_FUND,
            role="Quant Researcher Intern",
            programme=Programme.INTERNSHIP,
            date_applied=dt.date(2026, 10, 2),
            furthest_stage=FurthestStage.APPLIED,
            status=Status.REJECTED,
            last_update=dt.date(2026, 10, 8),
        ),
    ]


def _load() -> object:
    data = build_workbook(
        _apps(),
        tasks=[
            Task(
                task_id="t1",
                priority=Priority.HIGH,
                text="Email alumnus for referral",
                source=TaskSource.MANUAL,
            )
        ],
        scans=[
            ScanRun(
                started_at=dt.datetime(2026, 10, 9, 8, 41, tzinfo=dt.UTC),
                window_from=dt.datetime(2026, 10, 7, tzinfo=dt.UTC),
                new_apps=1,
                status_changes=2,
            )
        ],
    )
    return load_workbook(io.BytesIO(data))


def test_sheets_present() -> None:
    wb = _load()
    assert wb.sheetnames == ["Applications", "Priorities", "Summary", "Scan log"]


def test_applications_headers_and_table() -> None:
    wb = _load()
    ws = wb["Applications"]
    header = [c.value for c in ws[1]]
    assert header == APP_HEADERS
    assert "Applications" in ws.tables
    # Deadline (as in the personal tracker), then Email link and hidden App ID
    assert header[-3:] == ["Deadline", "Email link", "App ID"]
    assert ws.column_dimensions["O"].hidden is True


def test_applications_sorted_newest_first() -> None:
    wb = _load()
    ws = wb["Applications"]
    companies = [ws.cell(row=r, column=1).value for r in (2, 3)]
    assert companies == ["Example Bank", "Example Capital"]  # 05/10 before 02/10


def test_days_since_update_is_a_live_formula() -> None:
    wb = _load()
    ws = wb["Applications"]
    assert ws["J2"].value == '=IF(ISNUMBER(I2),TODAY()-I2,"")'


def test_status_dropdown_and_colour_rules_exist() -> None:
    wb = _load()
    ws = wb["Applications"]
    assert len(ws.data_validations.dataValidation) >= 3
    assert len(ws.conditional_formatting) >= 1


def test_summary_has_countif_formulas() -> None:
    wb = _load()
    s = wb["Summary"]
    assert s["B5"].value == "=COUNTIF(Applications!$H:$H,A5)"


def test_priorities_keeps_manual_rows() -> None:
    wb = _load()
    p = wb["Priorities"]
    rows = [[c.value for c in row] for row in p.iter_rows(min_row=2, values_only=False)]
    texts = [r[1] for r in rows]
    sources = [r[7] for r in rows]
    assert "Email alumnus for referral" in texts
    assert "Manual" in sources


def test_scan_log_written() -> None:
    wb = _load()
    sl = wb["Scan log"]
    assert sl["A1"].value == "Scan date"
    assert sl["C2"].value == 1  # new applications added


def test_matches_personal_tracker_look() -> None:
    wb = _load()
    ws = wb["Applications"]
    assert ws["A1"].fill.fgColor.rgb.endswith("1F3864")
    p = wb["Priorities"]
    assert "Priorities" in p.tables
    fills = {
        r.dxf.fill.fgColor.rgb[-6:]
        for rules in p.conditional_formatting._cf_rules.values()
        for r in rules
        if r.dxf and r.dxf.fill and r.dxf.fill.fgColor is not None and r.dxf.fill.fgColor.rgb
    }
    assert {"F8CBAD", "FFE699"} <= fills
    s = wb["Summary"]
    assert s["A1"].value == "Job applications, 2 Oct - 9 Oct 2026"


def test_priority_rules() -> None:
    from excel.builder import _priority_rows

    today = dt.date(2026, 10, 10)
    rows = _priority_rows(_apps(), [], [], today)
    # assessment with no dated deadline -> 2 High, ASAP; rejected app -> no row
    assert rows[0][0] == "2 - High" and rows[0][2] == "Example Bank" and rows[0][3] == "ASAP"
    assert all(r[2] != "Example Capital" for r in rows)
