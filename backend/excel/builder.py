"""Build the Job_Applications_Tracker.xlsx workbook from stored data.

Ports the layout of ``reference/build_tracker.py`` (fonts, widths, colours,
validations, conditional formats and Summary formulas) and the Priorities sheet
from the live tracker, driven by :class:`Application` / :class:`Deadline` /
:class:`Task` / :class:`ScanRun` data instead of hard-coded example rows.

Matches the personal tracker exactly: sheet order (Applications, Priorities,
Summary, Scan log), the Deadline column, the Priorities rules and colours
(red due in 3 days or less, amber in 7 or less or ASAP, grey when done), and
the Summary title with the date range. New vs the personal tracker: an
**Email link** column and a hidden **App ID** column after Deadline.
"""

from __future__ import annotations

import datetime as dt
import io
from collections import Counter

from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from domain.enums import (
    ACTIVE_STATUSES,
    FirmType,
    Priority,
    Programme,
    ProspectStatus,
    Status,
)
from domain.models import Application, Deadline, Prospect, ScanRun, Task

FONT = "Arial"
_THIN = Side(style="thin", color="D0D0D0")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HDR_FILL = PatternFill("solid", fgColor="1F3864")


def _cf_fill(colour: str) -> PatternFill:
    """Fill for conditional formatting. Excel takes a rule's colour from bgColor,
    so a fgColor-only fill (fine for normal cells) shows no colour in a rule."""

    return PatternFill(fill_type="solid", start_color=colour, end_color=colour)


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
    "Deadline",
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
    prospects: list[Prospect] | None = None,
) -> bytes:
    """Build the full workbook and return it as xlsx bytes."""

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Applications"
    next_deadline = _next_deadlines(deadlines or [])
    _build_applications(ws, apps, next_deadline)
    _build_priorities(wb.create_sheet("Priorities"), apps, deadlines or [], tasks or [])
    # Prospective roles sits right after Priorities (Requirement 5.1)
    if prospects:
        _build_prospects(wb.create_sheet("Prospective roles"), prospects)
    _build_summary(wb.create_sheet("Summary"), apps)
    _build_scan_log(wb.create_sheet("Scan log"), scans or [])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _next_deadlines(deadlines: list[Deadline]) -> dict[str, dt.date]:
    """Earliest open deadline per application."""

    out: dict[str, dt.date] = {}
    for d in deadlines:
        if d.done_at is not None:
            continue
        due = d.due_at.date()
        if d.app_id not in out or due < out[d.app_id]:
            out[d.app_id] = due
    return out


def _active(app: Application) -> bool:
    return app.status in ACTIVE_STATUSES


def _build_applications(
    ws: Worksheet, apps: list[Application], next_deadline: dict[str, dt.date] | None = None
) -> None:
    next_deadline = next_deadline or {}

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
                next_deadline.get(app.app_id) if app.status in ACTIVE_STATUSES else None,
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
        row[_COL["Deadline"]].number_format = "dd/mm/yyyy"
        row[_COL["Days since update"]].number_format = "0"
        row[_COL["Days since update"]].alignment = Alignment(vertical="top", horizontal="center")
        if row[_COL["Date applied"]].value == "Not in emails":
            row[_COL["Date applied"]].font = Font(name=FONT, size=10, italic=True, color="808080")
        if row[_COL["Next step"]].value == "None":
            row[_COL["Next step"]].font = Font(name=FONT, size=10, color="A0A0A0")

    widths = [22, 22, 42, 12, 18, 13, 20, 18, 12, 11, 34, 46, 12, 16, 14]
    for col_idx, w in enumerate(widths):
        ws.column_dimensions[_col_letter(col_idx)].width = w
    # App ID is kept for round-tripping edits but hidden from the user.
    ws.column_dimensions[_col_letter(_COL["App ID"])].hidden = True
    ws.freeze_panes = "B2"
    ws.row_dimensions[1].height = 30

    last_col = _col_letter(len(APP_HEADERS) - 1)
    # plain table (no built-in style) so the navy header and status colours show as-is
    ws.add_table(Table(displayName="Applications", ref=f"A1:{last_col}{n}"))

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
                fill=_cf_fill(colour),
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
            fill=_cf_fill("FFE5B4"),
            font=Font(name=FONT, bold=True, color="9C5700"),
        ),
    )


NOTES_SHOWN = 3  # latest notes kept in the cell, like the personal tracker
NOTE_MAX_CHARS = 70


def _short_note(text: str) -> str:
    """First sentence of a note, trimmed, so rows stay one or two lines tall."""

    t = " ".join(text.split())
    for sep in (". ", "; "):
        if sep in t:
            t = t.split(sep, 1)[0]
    t = t.rstrip(".")
    if len(t) > NOTE_MAX_CHARS:
        t = t[: NOTE_MAX_CHARS - 1].rstrip() + "\u2026"
    return t


def render_notes(app: Application) -> str:
    """Compact timeline: last few notes, one short line each, duplicates dropped."""

    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for n in sorted(app.notes, key=lambda x: x.date):
        short = _short_note(n.text)
        key = (n.date.isoformat(), short.lower())
        if not short or key in seen:
            continue
        seen.add(key)
        lines.append(f"{n.date.strftime('%d/%m')}: {short}")
    return "\n".join(lines[-NOTES_SHOWN:])


_render_notes = render_notes


def _email_link(app: Application) -> str:
    # The matcher stores each email's web link on the Event. Wiring the most
    # recent link through to the Applications sheet is done by the export layer
    # (task 8 integration); left blank until events are joined in.
    _ = app
    return ""


def _summary_title(apps: list[Application]) -> str:
    dates = [d for a in apps for d in (a.date_applied, a.last_update) if d]
    if not dates:
        return "Job applications"
    lo, hi = min(dates), max(dates)
    return f"Job applications, {lo.day} {lo:%b} - {hi.day} {hi:%b %Y}"


def _build_summary(s: Worksheet, apps: list[Application] | None = None) -> None:
    s["A1"] = _summary_title(apps or [])
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
    s.cell(t + 1, 1, "Still active (awaiting + assessment + interview + offer)").font = Font(
        name=FONT, size=10, italic=True
    )
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


_PRIO_BORDER = Border(
    left=Side(style="thin", color="BFBFBF"),
    right=Side(style="thin", color="BFBFBF"),
    top=Side(style="thin", color="BFBFBF"),
    bottom=Side(style="thin", color="BFBFBF"),
)
_PRIO_HEADERS = ["Priority", "Task", "Company", "Due date", "Days left", "Done?", "Notes", "Source"]


def _build_priorities(
    s: Worksheet,
    apps: list[Application],
    deadlines: list[Deadline],
    tasks: list[Task],
    today: dt.date | None = None,
) -> None:
    for j, h in enumerate(_PRIO_HEADERS, start=1):
        _hdr(s.cell(1, j, h))

    rows = _priority_rows(apps, deadlines, tasks, today or dt.date.today())
    for i, row in enumerate(rows, start=2):
        priority, task_text, company, due, done, notes, source = row
        values = [
            priority,
            task_text,
            company,
            due,
            f'=IF(ISNUMBER(D{i}),D{i}-TODAY(),"")',
            done,
            notes,
            source,
        ]
        for j, v in enumerate(values, start=1):
            c = s.cell(i, j, v)
            c.font = Font(name=FONT, size=10)
            c.border = _PRIO_BORDER
            c.alignment = Alignment(
                wrap_text=True, vertical="top", horizontal="center" if j in (4, 5, 6, 8) else None
            )
        s.cell(i, 4).number_format = "dd/mm/yyyy"

    n = max(len(rows) + 1, 2)
    tab = Table(displayName="Priorities", ref=f"A1:H{n}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
    s.add_table(tab)

    dv_done = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    s.add_data_validation(dv_done)
    dv_done.add("F2:F200")
    dv_src = DataValidation(type="list", formula1='"Auto,Manual"', allow_blank=True)
    s.add_data_validation(dv_src)
    dv_src.add("H2:H200")

    # done = grey; due in 3 days or less = red; due in 7 or less, or ASAP = amber
    s.conditional_formatting.add(
        "A2:G200",
        FormulaRule(
            formula=['$F2="Yes"'],
            font=Font(name=FONT, size=10, color="A6A6A6", strike=True),
            stopIfTrue=True,
        ),
    )
    s.conditional_formatting.add(
        "A2:G200",
        FormulaRule(formula=["AND(ISNUMBER($E2),$E2<=3)"], fill=_cf_fill("F8CBAD")),
    )
    s.conditional_formatting.add(
        "A2:G200",
        FormulaRule(formula=["AND(ISNUMBER($E2),$E2<=7)"], fill=_cf_fill("FFE699")),
    )
    s.conditional_formatting.add(
        "A2:G200",
        FormulaRule(formula=['$D2="ASAP"'], fill=_cf_fill("FFE699")),
    )

    for col, w in zip("ABCDEFGH", [10, 55, 22, 12, 10, 9, 50, 10], strict=True):
        s.column_dimensions[col].width = w
    s.freeze_panes = "A2"


def _prio_for(due: dt.date | None, status: Status, today: dt.date) -> str:
    if status in (Status.INTERVIEW, Status.OFFER):
        return Priority.URGENT.value
    if due is not None:
        left = (due - today).days
        if left <= 3:
            return Priority.URGENT.value
        if left <= 7:
            return Priority.HIGH.value
        return Priority.MEDIUM.value
    return Priority.HIGH.value


def _priority_rows(
    apps: list[Application],
    deadlines: list[Deadline],
    tasks: list[Task],
    today: dt.date | None = None,
) -> list[tuple[object, ...]]:
    """Same rules as the personal tracker's update_priorities.py.

    1 Urgent: due in 3 days or less, or an interview/offer. 2 High: due in 7 days
    or less, undated assessments, Check email items. 3 Medium: later deadlines,
    unfinished applications. 4 Low: follow-ups after 21+ days with no news.
    """

    today = today or dt.date.today()
    next_deadline = _next_deadlines(deadlines)
    counts = Counter(a.company for a in apps)
    rows: list[tuple[object, ...]] = []
    covered: set[str] = set()

    def label(app: Application) -> str:
        if counts[app.company] > 1 and app.role:
            return f"{app.company} ({app.role.split(' - ')[-1][:40]})"
        return app.company

    for app in apps:
        nxt = (app.next_step or "").strip()
        due = next_deadline.get(app.app_id)
        lu = app.last_update
        stamp = f"{app.status.value}; last update {lu.strftime('%d/%m') if lu else '?'}"
        waiting = nxt.lower().startswith("wait") or nxt in ("", "None")
        co = label(app)
        st = app.status
        if st in (Status.ASSESSMENT_STAGE, Status.INTERVIEW, Status.OFFER) and nxt != "None":
            rows.append(
                (
                    _prio_for(due, st, today),
                    nxt or "Check next step",
                    co,
                    due or "ASAP",
                    "No",
                    stamp,
                    "Auto",
                )
            )
            covered.add(app.app_id)
        elif st == Status.CHECK_EMAIL:
            rows.append(
                (
                    Priority.HIGH.value,
                    nxt or "Open the latest email and record the outcome",
                    co,
                    "ASAP",
                    "No",
                    stamp,
                    "Auto",
                )
            )
            covered.add(app.app_id)
        elif st == Status.NOT_SUBMITTED and nxt != "None":
            rows.append((Priority.MEDIUM.value, nxt, co, due or "When free", "No", stamp, "Auto"))
            covered.add(app.app_id)
        elif st == Status.AWAITING_RESPONSE and not waiting:
            rows.append((_prio_for(due, st, today), nxt, co, due or "ASAP", "No", stamp, "Auto"))
            covered.add(app.app_id)
        elif st == Status.NO_RESPONSE and nxt != "None":
            rows.append((Priority.LOW.value, nxt, co, "When free", "No", stamp, "Auto"))
        if (
            st in (Status.AWAITING_RESPONSE, Status.ASSESSMENT_STAGE)
            and lu is not None
            and (today - lu).days >= 21
            and waiting
        ):
            rows.append(
                (
                    Priority.LOW.value,
                    f"Consider polite follow-up (no news since {lu.strftime('%d/%m')})",
                    co,
                    "When free",
                    "No",
                    stamp,
                    "Auto",
                )
            )

    # open deadlines not already shown against their application
    app_by_id = {a.app_id: a for a in apps}
    for d in deadlines:
        if d.done_at is not None or d.app_id in covered:
            continue
        owner = app_by_id.get(d.app_id)
        if owner is not None and owner.status not in ACTIVE_STATUSES:
            continue
        due = d.due_at.date()
        status = owner.status if owner else Status.AWAITING_RESPONSE
        rows.append(
            (
                _prio_for(due, status, today),
                d.what,
                label(owner) if owner else None,
                due,
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
                task.due or "ASAP",
                "Yes" if task.done_at else "No",
                task.notes or "",
                task.source.value,
            )
        )

    def order(r: tuple[object, ...]) -> tuple[object, ...]:
        due = r[3]
        kind = 0 if isinstance(due, dt.date) else 1 if due == "ASAP" else 2
        return (r[4] == "Yes", str(r[0]), kind, due if isinstance(due, dt.date) else dt.date.max)

    rows.sort(key=order)
    return rows


PROSPECT_HEADERS = [
    "Found",
    "Posted",
    "Company",
    "Role",
    "Programme",
    "Location",
    "Closing date",
    "Fit",
    "Why",
    "Link",
    "Source",
    "Status",
]
_PCOL = {h: i for i, h in enumerate(PROSPECT_HEADERS)}
PROSPECT_STATUS_VALUES = [s.value for s in ProspectStatus]
_PROSPECT_WIDTHS = [11, 11, 22, 40, 12, 14, 12, 6, 40, 12, 12, 12]
# New and Interested first, so the user sees fresh roles at the top.
_PROSPECT_STATUS_ORDER = {
    ProspectStatus.NEW.value: 0,
    ProspectStatus.INTERESTED.value: 1,
    ProspectStatus.APPLIED.value: 2,
    ProspectStatus.NOT_FOR_ME.value: 3,
}


def _prospect_sort_key(p: Prospect) -> tuple[int, int, int, dt.date]:
    """Status (New/Interested first), Fit (high first), Posted (newest), Closing (soonest)."""

    status_rank = _PROSPECT_STATUS_ORDER.get(p.status.value, 9)
    posted = -(p.posted_date.toordinal()) if p.posted_date else 0
    return (status_rank, -p.fit, posted, p.closing_date or dt.date.max)


def _build_prospects(s: Worksheet, prospects: list[Prospect], today: dt.date | None = None) -> None:
    today = today or dt.date.today()
    for j, h in enumerate(PROSPECT_HEADERS, start=1):
        _hdr(s.cell(1, j, h))

    rows = sorted(prospects, key=_prospect_sort_key)
    for i, p in enumerate(rows, start=2):
        link_cell_col = _col_letter(_PCOL["Link"])
        values = [
            p.found_at,
            p.posted_date,
            p.company or "",
            p.role or "",
            p.programme.value,
            p.location or "",
            p.closing_date,
            p.fit,
            p.why,
            "Open",  # text; hyperlink added below
            p.source or _source_from_url(p.url),
            p.status.value,
        ]
        for j, v in enumerate(values, start=1):
            c = s.cell(i, j, v)
            c.font = Font(name=FONT, size=10)
            c.border = _BORDER
            c.alignment = Alignment(
                vertical="top",
                wrap_text=True,
                horizontal="center" if j - 1 in (_PCOL["Fit"], _PCOL["Programme"]) else None,
            )
        s.cell(i, _PCOL["Found"] + 1).number_format = "dd/mm/yyyy"
        s.cell(i, _PCOL["Posted"] + 1).number_format = "dd/mm/yyyy"
        s.cell(i, _PCOL["Closing date"] + 1).number_format = "dd/mm/yyyy"
        # clickable hyperlink on the Link cell (Requirement 5.5)
        link = s.cell(i, _PCOL["Link"] + 1)
        if p.url:
            link.hyperlink = p.url
            link.font = Font(name=FONT, size=10, color="0563C1", underline="single")
        _ = link_cell_col

    n = max(len(rows) + 1, 2)
    tab = Table(displayName="Prospects", ref=f"A1:{_col_letter(len(PROSPECT_HEADERS) - 1)}{n}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
    s.add_table(tab)

    # Status dropdown (Requirement 5.3)
    status_col = _col_letter(_PCOL["Status"])
    dv = DataValidation(
        type="list", formula1='"' + ",".join(PROSPECT_STATUS_VALUES) + '"', allow_blank=True
    )
    s.add_data_validation(dv)
    dv.add(f"{status_col}2:{status_col}{n + 200}")

    posted_col = _col_letter(_PCOL["Posted"])
    # posted in the last 7 days -> green on the Posted cell ("new this week")
    s.conditional_formatting.add(
        f"{posted_col}2:{posted_col}{n + 200}",
        FormulaRule(
            formula=[f"AND(ISNUMBER(${posted_col}2),TODAY()-${posted_col}2<=7)"],
            fill=_cf_fill("C6EFCE"),
        ),
    )
    close_col = _col_letter(_PCOL["Closing date"])
    # closing within 7 days -> amber (Requirement 5.4)
    s.conditional_formatting.add(
        f"A2:{status_col}{n + 200}",
        FormulaRule(
            formula=[f"AND(ISNUMBER(${close_col}2),${close_col}2-TODAY()>=0,"
                     f"${close_col}2-TODAY()<=7)"],
            fill=_cf_fill("FFE699"),
        ),
    )
    # past closing date -> grey font
    s.conditional_formatting.add(
        f"A2:{status_col}{n + 200}",
        FormulaRule(
            formula=[f"AND(ISNUMBER(${close_col}2),${close_col}2<TODAY())"],
            font=Font(name=FONT, size=10, color="A6A6A6"),
        ),
    )
    # Applied / Not for me -> grey font (and wins, so put last with stopIfTrue)
    s.conditional_formatting.add(
        f"A2:{status_col}{n + 200}",
        FormulaRule(
            formula=[f'OR(${status_col}2="Applied",${status_col}2="Not for me")'],
            font=Font(name=FONT, size=10, color="A6A6A6"),
            stopIfTrue=True,
        ),
    )

    for col_idx, w in enumerate(_PROSPECT_WIDTHS):
        s.column_dimensions[_col_letter(col_idx)].width = w
    s.freeze_panes = "A2"
    s.row_dimensions[1].height = 24


def _source_from_url(url: str) -> str:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    parts = host.split(".")
    return parts[-2].capitalize() if len(parts) >= 2 else host


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
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = _HDR_FILL
    s.freeze_panes = "A2"
    for i, scan in enumerate(sorted(scans, key=lambda x: x.started_at), start=2):
        searched_from = scan.window_from.date() if scan.window_from else ""
        notes = "; ".join(scan.errors) if scan.errors else ""
        s.append([scan.started_at.date(), searched_from, scan.new_apps, scan.status_changes, notes])
        s.cell(i, 1).number_format = "dd/mm/yyyy"
        s.cell(i, 2).number_format = "dd/mm/yyyy"
        for cell in s[i]:
            cell.font = Font(name=FONT, size=10)
    for col, w in zip("ABCDE", [12, 18, 14, 13, 80], strict=True):
        s.column_dimensions[col].width = w


def _col_letter(idx0: int) -> str:
    """Convert a 0-based column index to an Excel column letter."""

    idx = idx0 + 1
    letters = ""
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters
