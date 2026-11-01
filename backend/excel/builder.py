"""Build the Job_Applications_Tracker.xlsx workbook from stored data.

Ports the layout of ``reference/build_tracker.py`` (fonts, widths, colours,
validations, conditional formats and Summary formulas) and the Priorities sheet
from the live tracker, driven by :class:`Application` / :class:`Deadline` /
:class:`Task` / :class:`ScanRun` data instead of hard-coded example rows.

New in v1 vs the reference: an **Email link** column and a hidden **App ID**
column on the Applications sheet.
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from domain.enums import (
    ACTIVE_STATUSES,
    FirmType,
    Programme,
    Status,
)
from domain.models import Application, Deadline, ScanRun, Task

FONT = "Arial"
_THIN = Side(style="thin", color="D0D0D0")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HDR_FILL = PatternFill("solid", fgColor="1F3864")

# Applications columns A..N (note the two new trailing columns).
APP_HEADERS = [
    "Company",
    "Firm type",
    "Role",
    "Programme",
    "Applied via",
    "Date applied",
    "Furthest stage",
    "Status",
    "Last update",
    "Days since update",
    "Next step",
    "Notes",
    "Email link",
    "App ID",
]
# 0-based indices for columns we touch by name downstream.
_COL = {h: i for i, h in enumerate(APP_HEADERS)}

STATUS_VALUES = [s.value for s in Status]
FIRM_VALUES = [f.value for f in FirmType]
PROGRAMME_VALUES = [p.value for p in Programme]

_STATUS_COLOURS = {
    Status.REJECTED.value: "F8D7DA",
    Status.CLOSED.value: "E2E3E5",
    Status.CLOSED_BY_EMPLOYER.value: "E2E3E5",
    Status.ASSESSMENT_STAGE.value: "FFF3CD",
    Status.INTERVIEW.value: "D1E7DD",
    Status.OFFER.value: "A3CFBB",
    Status.AWAITING_RESPONSE.value: "DCEBFA",
    Status.NO_RESPONSE.value: "F2F2F2",
    Status.NOT_SUBMITTED.value: "F2F2F2",
    Status.CHECK_EMAIL.value: "FFE5B4",
}


def _hdr(cell: object) -> None:
    cell.font = Font(name=FONT, bold=True, color="FFFFFF")  # type: ignore[attr-defined]
    cell.fill = _HDR_FILL  # type: ignore[attr-defined]
    cell.alignment = Alignment(vertical="center", wrap_text=True)  # type: ignore[attr-defined]


def build_workbook(
    apps: list[Application],
    deadlines: list[Deadline] | None = None,
    tasks: list[Task] | None = None,
    scans: list[ScanRun] | None = None,
) -> bytes:
    """Build the full workbook and return it as xlsx bytes."""

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Applications"
    _build_applications(ws, apps)
    _build_summary(wb.create_sheet("Summary"))
    _build_priorities(wb.create_sheet("Priorities"), apps, deadlines or [], tasks or [])
    _build_scan_log(wb.create_sheet("Scan log"), scans or [])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _active(app: Application) -> bool:
    return app.status in ACTIVE_STATUSES


def _build_applications(ws: Worksheet, apps: list[Application]) -> None:
    # sort newest first by (date_applied or last_update)
    def sort_key(a: Application) -> str:
        d = a.date_applied or a.last_update
        return d.isoformat() if d else ""

    rows = sorted(apps, key=sort_key, reverse=True)

    ws.append(APP_HEADERS)
    for i, app in enumerate(rows, start=2):
        days_formula = f'=IF(ISNUMBER(I{i}),TODAY()-I{i},"")'
        ws.append(
            [
                app.company,
                app.firm_type.value,
                app.role or "Role not stated in email",
                app.programme.value,
                app.applied_via or "Direct",
                app.date_applied if app.date_applied else "Not in emails",
                app.furthest_stage.value if app.furthest_stage else "",
                app.status.value,
                app.last_update,
                days_formula,
                app.next_step or "None",
                _render_notes(app),
                _email_link(app),
                app.app_id,
            ]
        )

    n = len(rows) + 1
    for cell in ws[1]:
        _hdr(cell)
    for row in ws.iter_rows(min_row=2, max_row=n):
        for cell in row:
            cell.font = Font(name=FONT, size=10)
            cell.border = _BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        row[_COL["Date applied"]].number_format = "dd/mm/yyyy"
        row[_COL["Last update"]].number_format = "dd/mm/yyyy"
        row[_COL["Days since update"]].number_format = "0"
        row[_COL["Days since update"]].alignment = Alignment(vertical="top", horizontal="center")
        if row[_COL["Date applied"]].value == "Not in emails":
            row[_COL["Date applied"]].font = Font(name=FONT, size=10, italic=True, color="808080")
        if row[_COL["Next step"]].value == "None":
            row[_COL["Next step"]].font = Font(name=FONT, size=10, color="A0A0A0")

    widths = [22, 22, 42, 12, 18, 13, 20, 18, 12, 11, 34, 46, 16, 14]
    for col_idx, w in enumerate(widths):
        ws.column_dimensions[_col_letter(col_idx)].width = w
    # App ID is kept for round-tripping edits but hidden from the user.
    ws.column_dimensions[_col_letter(_COL["App ID"])].hidden = True
    ws.freeze_panes = "B2"
    ws.row_dimensions[1].height = 30

    last_col = _col_letter(len(APP_HEADERS) - 1)
    tab = Table(displayName="Applications", ref=f"A1:{last_col}{n}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
    ws.add_table(tab)

    # drop-downs for Status, Firm type, Programme
    for header, opts in (
        ("Status", STATUS_VALUES),
        ("Firm type", FIRM_VALUES),
        ("Programme", PROGRAMME_VALUES),
    ):
        col = _col_letter(_COL[header])
        dv = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{n + 200}")

    status_col = _col_letter(_COL["Status"])
    for status_value, colour in _STATUS_COLOURS.items():
        ws.conditional_formatting.add(
            f"{status_col}2:{status_col}{n + 200}",
            FormulaRule(
                formula=[f'${status_col}2="{status_value}"'],
                fill=PatternFill("solid", fgColor=colour),
            ),
        )

    # amber flag: active application, no news for 21+ days
    days_col = _col_letter(_COL["Days since update"])
    ws.conditional_formatting.add(
        f"{days_col}2:{days_col}{n + 200}",
        FormulaRule(
            formula=[
                f"AND(ISNUMBER(${days_col}2),${days_col}2>=21,"
                f'OR(${status_col}2="Awaiting response",${status_col}2="Assessment stage"))'
            ],
            fill=PatternFill("solid", fgColor="FFE5B4"),
            font=Font(name=FONT, bold=True, color="9C5700"),
        ),
    )


def _render_notes(app: Application) -> str:
    return "\n".join(f"{n.date.strftime('%d/%m')}: {n.text}" for n in app.notes)


def _email_link(app: Application) -> str:
    # The matcher stores each email's web link on the Event. Wiring the most
    # recent link through to the Applications sheet is done by the export layer
    # (task 8 integration); left blank until events are joined in.
    _ = app
    return ""


def _build_summary(s: Worksheet) -> None:
    s["A1"] = "Job applications"
    s["A1"].font = Font(name=FONT, bold=True, size=14)

    s["A3"] = "By status"
    s["A3"].font = Font(name=FONT, bold=True, size=11)
    s["A4"], s["B4"] = "Status", "Count"
    _hdr(s["A4"])
    _hdr(s["B4"])
    for i, status_value in enumerate(STATUS_VALUES, start=5):
        s.cell(i, 1, status_value).font = Font(name=FONT)
        s.cell(i, 2, f"=COUNTIF(Applications!$H:$H,A{i})").font = Font(name=FONT)
    t = 5 + len(STATUS_VALUES)
    s.cell(t, 1, "Total").font = Font(name=FONT, bold=True)
    s.cell(t, 2, f"=SUM(B5:B{t - 1})").font = Font(name=FONT, bold=True)
    s.cell(
        t + 1, 1, "Still active (awaiting + assessment + interview + offer)"
    ).font = Font(name=FONT, size=10, italic=True)
    s.cell(t + 1, 2, "=SUM(B5:B8)").font = Font(name=FONT, size=10, italic=True)

    # by firm type
    s["D3"] = "By firm type"
    s["D3"].font = Font(name=FONT, bold=True, size=11)
    heads = [
        "Firm type",
        "Applications",
        "Still active",
        "Rejected / closed",
        "Got past application",
    ]
    for j, h in enumerate(heads):
        _hdr(s.cell(4, 4 + j, h))
    n_guard = 200
    for i, firm_value in enumerate(FIRM_VALUES, start=5):
        s.cell(i, 4, firm_value).font = Font(name=FONT)
        s.cell(i, 5, f"=COUNTIF(Applications!$B:$B,D{i})")
        s.cell(
            i,
            6,
            f'=COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Awaiting response")'
            f'+COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Assessment stage")'
            f'+COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Interview")'
            f'+COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Offer")',
        )
        s.cell(
            i,
            7,
            f'=COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Rejected")'
            f'+COUNTIFS(Applications!$B:$B,D{i},Applications!$H:$H,"Closed*")',
        )
        s.cell(
            i,
            8,
            f"=SUMPRODUCT((Applications!$B$2:$B${n_guard}=D{i})"
            f'*(Applications!$G$2:$G${n_guard}<>"Applied")'
            f'*(Applications!$G$2:$G${n_guard}<>"Started")'
            f'*(Applications!$G$2:$G${n_guard}<>""))',
        )
        for j in range(5, 9):
            s.cell(i, j).font = Font(name=FONT)
            s.cell(i, j).alignment = Alignment(horizontal="center")
    ft_end = 4 + len(FIRM_VALUES)
    s.cell(ft_end + 1, 4, "Total").font = Font(name=FONT, bold=True)
    for j, col in zip(range(5, 9), "EFGH", strict=True):
        c = s.cell(ft_end + 1, j, f"=SUM({col}5:{col}{ft_end})")
        c.font = Font(name=FONT, bold=True)
        c.alignment = Alignment(horizontal="center")

    # by programme
    p0 = t + 4
    s.cell(p0, 1, "By programme").font = Font(name=FONT, bold=True, size=11)
    _hdr(s.cell(p0 + 1, 1, "Programme"))
    _hdr(s.cell(p0 + 1, 2, "Count"))
    for k, prog_value in enumerate(PROGRAMME_VALUES, start=p0 + 2):
        s.cell(k, 1, prog_value).font = Font(name=FONT)
        s.cell(k, 2, f"=COUNTIF(Applications!$D:$D,A{k})").font = Font(name=FONT)

    for col, w in (("A", 34), ("B", 9), ("C", 3), ("D", 24)):
        s.column_dimensions[col].width = w
    for col in "EFGH":
        s.column_dimensions[col].width = 14
    s.row_dimensions[4].height = 30


def _build_priorities(
    s: Worksheet,
    apps: list[Application],
    deadlines: list[Deadline],
    tasks: list[Task],
) -> None:
    headers = ["Priority", "Task", "Company", "Due date", "Days left", "Done?", "Notes", "Source"]
    s.append(headers)
    for cell in s[1]:
        _hdr(cell)

    rows = _priority_rows(apps, deadlines, tasks)
    for i, row in enumerate(rows, start=2):
        priority, task_text, company, due, done, notes, source = row
        days_left = f'=IF(ISNUMBER(D{i}),D{i}-TODAY(),"")'
        s.append([priority, task_text, company, due, days_left, done, notes, source])
        s.cell(i, 4).number_format = "dd/mm/yyyy"
        for cell in s[i]:
            cell.font = Font(name=FONT, size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    n = len(rows) + 1
    dv_done = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    s.add_data_validation(dv_done)
    dv_done.add(f"F2:F{n + 200}")
    dv_src = DataValidation(type="list", formula1='"Auto,Manual"', allow_blank=True)
    s.add_data_validation(dv_src)
    dv_src.add(f"H2:H{n + 200}")

    for col, w in zip("ABCDEFGH", [12, 42, 22, 14, 10, 8, 40, 10], strict=True):
        s.column_dimensions[col].width = w
    s.freeze_panes = "A2"


def _priority_rows(
    apps: list[Application],
    deadlines: list[Deadline],
    tasks: list[Task],
) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    app_by_id = {a.app_id: a for a in apps}

    for d in deadlines:
        if d.done_at is not None:
            continue
        app = app_by_id.get(d.app_id)
        company = app.company if app else None
        rows.append(("2 - High", d.what, company, d.due_at.date(), "No", "", "Auto"))

    for app in apps:
        if app.status in ACTIVE_STATUSES and app.next_step and app.next_step != "None":
            rows.append(("2 - High", app.next_step, app.company, None, "No", "", "Auto"))
        if app.status == Status.CHECK_EMAIL:
            rows.append(
                (
                    "2 - High",
                    "Open the email to confirm the outcome",
                    app.company,
                    None,
                    "No",
                    "",
                    "Auto",
                )
            )

    # manual rows (preserved verbatim across exports)
    for task in tasks:
        rows.append(
            (
                task.priority.value,
                task.text,
                task.company,
                task.due,
                "Yes" if task.done_at else "No",
                task.notes or "",
                task.source.value,
            )
        )
    return rows


def _build_scan_log(s: Worksheet, scans: list[ScanRun]) -> None:
    headers = [
        "Scan date",
        "Emails searched from",
        "New applications added",
        "Status changes",
        "Notes",
    ]
    s.append(headers)
    for cell in s[1]:
        _hdr(cell)
    for i, scan in enumerate(sorted(scans, key=lambda x: x.started_at), start=2):
        searched_from = scan.window_from.date() if scan.window_from else ""
        notes = "; ".join(scan.errors) if scan.errors else ""
        s.append(
            [scan.started_at.date(), searched_from, scan.new_apps, scan.status_changes, notes]
        )
        s.cell(i, 1).number_format = "dd/mm/yyyy"
        s.cell(i, 2).number_format = "dd/mm/yyyy"
        for cell in s[i]:
            cell.font = Font(name=FONT, size=10)
    for col, w in zip("ABCDE", [14, 20, 22, 16, 50], strict=True):
        s.column_dimensions[col].width = w


def _col_letter(idx0: int) -> str:
    """Convert a 0-based column index to an Excel column letter."""

    idx = idx0 + 1
    letters = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters
