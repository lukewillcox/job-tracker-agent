"""Tests for the Prospective roles Excel sheet + Status importer (Task 6)."""

from __future__ import annotations

import datetime as dt
import io

from openpyxl import load_workbook

from domain.enums import Programme, ProspectStatus
from domain.models import Prospect
from excel.builder import PROSPECT_HEADERS, build_workbook
from excel.importer import import_prospect_status


def _prospects() -> list[Prospect]:
    return [
        Prospect(
            prospect_id="p1", url="https://jobs.janestreet.com/trader",
            company="Jane Street", company_norm="jane street", role="Quant Trader",
            programme=Programme.GRADUATE, location="London",
            closing_date=dt.date(2026, 11, 3), fit=5, why="python + london",
            source="Janestreet", status=ProspectStatus.NEW,
            found_at=dt.date(2026, 10, 20), last_seen=dt.date(2026, 11, 1),
        ),
        Prospect(
            prospect_id="p2", url="https://www.linkedin.com/jobs/view/2",
            company="Citadel", company_norm="citadel", role="SWE Intern",
            programme=Programme.INTERNSHIP, location="London",
            closing_date=None, fit=3, why="skills match", source="Linkedin",
            status=ProspectStatus.APPLIED,
            found_at=dt.date(2026, 10, 1), last_seen=dt.date(2026, 10, 25),
        ),
        Prospect(
            prospect_id="p3", url="https://grb.uk.com/role/3",
            company="Optiver", company_norm="optiver", role="Graduate Trader",
            programme=Programme.GRADUATE, location="Amsterdam",
            closing_date=dt.date(2027, 1, 10), fit=4, why="trading focus",
            source="Grb", status=ProspectStatus.INTERESTED,
            found_at=dt.date(2026, 10, 28), last_seen=dt.date(2026, 11, 1),
        ),
    ]


def _load(prospects: list[Prospect]):
    data = build_workbook([], prospects=prospects)
    wb = load_workbook(io.BytesIO(data))
    return wb


def test_sheet_present_after_priorities() -> None:
    wb = _load(_prospects())
    names = wb.sheetnames
    assert "Prospective roles" in names
    assert names.index("Prospective roles") == names.index("Priorities") + 1


def test_headers_and_order() -> None:
    wb = _load(_prospects())
    ws = wb["Prospective roles"]
    header = [c.value for c in ws[1]]
    assert header == PROSPECT_HEADERS
    # sort: New (p1) and Interested (p3) first, then Applied (p2)
    statuses = [ws.cell(r, PROSPECT_HEADERS.index("Status") + 1).value for r in (2, 3, 4)]
    assert statuses[0] in ("New", "Interested")
    assert statuses[-1] == "Applied"


def test_new_sorted_by_fit() -> None:
    wb = _load(_prospects())
    ws = wb["Prospective roles"]
    # row 2 should be the New p1 (fit 5), row 3 the Interested p3 (fit 4)
    companies = [ws.cell(r, PROSPECT_HEADERS.index("Company") + 1).value for r in (2, 3)]
    assert companies[0] == "Jane Street"


def test_link_is_a_hyperlink() -> None:
    wb = _load(_prospects())
    ws = wb["Prospective roles"]
    link_col = PROSPECT_HEADERS.index("Link") + 1
    cell = ws.cell(2, link_col)
    assert cell.hyperlink is not None
    assert "janestreet" in cell.hyperlink.target


def test_status_dropdown_present() -> None:
    wb = _load(_prospects())
    ws = wb["Prospective roles"]
    formulas = [dv.formula1 for dv in ws.data_validations.dataValidation]
    assert any("New" in f and "Not for me" in f for f in formulas)


def test_no_sheet_when_no_prospects() -> None:
    wb = load_workbook(io.BytesIO(build_workbook([])))
    assert "Prospective roles" not in wb.sheetnames


# --- importer round-trip -------------------------------------------------
def test_import_prospect_status_by_url() -> None:
    data = build_workbook([], prospects=_prospects())
    # simulate the user changing p1's Status to "Not for me"
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Prospective roles"]
    status_col = PROSPECT_HEADERS.index("Status") + 1
    ws.cell(2, status_col).value = "Not for me"
    buf = io.BytesIO()
    wb.save(buf)

    edits = import_prospect_status(buf.getvalue())
    by_url = {e.url: e.status for e in edits}
    assert by_url["https://jobs.janestreet.com/trader"] == ProspectStatus.NOT_FOR_ME
    # unchanged rows still report their stored status
    assert by_url["https://www.linkedin.com/jobs/view/2"] == ProspectStatus.APPLIED


def test_import_returns_empty_without_sheet() -> None:
    assert import_prospect_status(build_workbook([])) == []
