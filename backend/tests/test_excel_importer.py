import datetime as dt
import io

from openpyxl import load_workbook

from domain.enums import FirmType, FurthestStage, Programme, Status
from domain.models import Application, Note
from excel.builder import build_workbook
from excel.importer import import_edits


def _apps() -> list[Application]:
    return [
        Application(
            app_id="a1",
            company="Example Bank",
            company_norm="example bank",
            firm_type=FirmType.INVESTMENT_BANK,
            role="Graduate Analyst",
            programme=Programme.GRADUATE,
            status=Status.AWAITING_RESPONSE,
            furthest_stage=FurthestStage.APPLIED,
            last_update=dt.date(2026, 10, 9),
            next_step="None",
            notes=[Note(date=dt.date(2026, 10, 9), text="application received")],
        ),
    ]


def _roundtrip_with_edit(column_header: str, new_value: str) -> list:
    apps = _apps()
    data = build_workbook(apps)
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Applications"]
    header = [c.value for c in ws[1]]
    col = header.index(column_header) + 1
    ws.cell(row=2, column=col, value=new_value)
    buf = io.BytesIO()
    wb.save(buf)
    return import_edits(buf.getvalue(), apps).edits


def test_detects_status_edit() -> None:
    edits = _roundtrip_with_edit("Status", "Rejected")
    assert len(edits) == 1
    assert edits[0].field == "status"
    assert edits[0].new_value == Status.REJECTED
    assert edits[0].app_id == "a1"


def test_detects_firm_type_edit() -> None:
    edits = _roundtrip_with_edit("Firm type", "Hedge fund")
    assert any(e.field == "firm_type" and e.new_value == FirmType.HEDGE_FUND for e in edits)


def test_no_edit_when_unchanged() -> None:
    apps = _apps()
    data = build_workbook(apps)
    result = import_edits(data, apps)
    assert result.edits == []
    assert result.problems == []


def test_unknown_status_flagged_as_problem() -> None:
    apps = _apps()
    data = build_workbook(apps)
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Applications"]
    header = [c.value for c in ws[1]]
    ws.cell(row=2, column=header.index("Status") + 1, value="Totally Bogus")
    buf = io.BytesIO()
    wb.save(buf)
    result = import_edits(buf.getvalue(), apps)
    assert any("unknown Status" in p for p in result.problems)


def test_next_step_edit_detected() -> None:
    edits = _roundtrip_with_edit("Next step", "Prepare for interview")
    assert any(e.field == "next_step" and e.new_value == "Prepare for interview" for e in edits)
