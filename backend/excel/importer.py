"""Read user edits back from the Excel workbook.

Reads the Applications table by header name (not column position) and the hidden
App ID column, diffs the editable fields (Status, Firm type, Programme, Next
step, Notes) against stored values, and reads the Priorities sheet (Done? = Yes
marks items done; new Manual rows become tasks). See design.md "Excel export".
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from openpyxl import load_workbook

from domain.enums import FirmType, Priority, Programme, Status, TaskSource
from domain.models import Application, Task

__all__ = [
    "ImportResult",
    "ManualEdit",
    "import_edits",
]

# Fields the user may edit in the Applications sheet (Requirement 6.3).
_EDITABLE_FIELDS = ("status", "firm_type", "programme", "next_step", "notes")

# header text -> (field name, parser)
_STATUS_BY_VALUE = {s.value: s for s in Status}
_FIRM_BY_VALUE = {f.value: f for f in FirmType}
_PROG_BY_VALUE = {p.value: p for p in Programme}
_PRIORITY_BY_VALUE = {p.value: p for p in Priority}


@dataclass(frozen=True)
class ManualEdit:
    """A single field the user changed in the workbook."""

    app_id: str
    field: str
    new_value: object


@dataclass
class ImportResult:
    edits: list[ManualEdit] = field(default_factory=list)
    done_app_ids: list[str] = field(default_factory=list)  # deadlines/tasks marked done
    manual_tasks: list[Task] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _header_index(header_row: tuple[object, ...]) -> dict[str, int]:
    return {str(c): i for i, c in enumerate(header_row) if c is not None}


def import_edits(xlsx_bytes: bytes, apps: list[Application]) -> ImportResult:
    """Diff the workbook against stored applications and read Priorities edits."""

    result = ImportResult()
    wb = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    by_id = {a.app_id: a for a in apps}

    if "Applications" in wb.sheetnames:
        _import_applications(wb["Applications"], by_id, result)
    if "Priorities" in wb.sheetnames:
        _import_priorities(wb["Priorities"], result)
    return result


def _import_applications(ws: object, by_id: dict[str, Application], result: ImportResult) -> None:
    rows = list(ws.iter_rows(values_only=True))  # type: ignore[attr-defined]
    if not rows:
        return
    cols = _header_index(rows[0])
    required = {"App ID", "Status", "Firm type", "Programme", "Next step", "Notes"}
    missing = required - cols.keys()
    if missing:
        result.problems.append(f"Applications sheet missing columns: {sorted(missing)}")
        return

    for row in rows[1:]:
        app_id = row[cols["App ID"]]
        if not app_id:
            continue
        app = by_id.get(str(app_id))
        if app is None:
            result.problems.append(f"Row references unknown App ID {app_id!r}")
            continue
        _diff_row(app, row, cols, result)


def _diff_row(
    app: Application,
    row: tuple[object, ...],
    cols: dict[str, int],
    result: ImportResult,
) -> None:
    # Status
    raw_status = _cell(row, cols, "Status")
    if raw_status and raw_status in _STATUS_BY_VALUE:
        new = _STATUS_BY_VALUE[raw_status]
        if new != app.status:
            result.edits.append(ManualEdit(app.app_id, "status", new))
    elif raw_status and raw_status not in _STATUS_BY_VALUE:
        result.problems.append(f"{app.company}: unknown Status {raw_status!r}")

    # Firm type
    raw_firm = _cell(row, cols, "Firm type")
    if raw_firm and raw_firm in _FIRM_BY_VALUE:
        new_ft = _FIRM_BY_VALUE[raw_firm]
        if new_ft != app.firm_type:
            result.edits.append(ManualEdit(app.app_id, "firm_type", new_ft))
    elif raw_firm and raw_firm not in _FIRM_BY_VALUE:
        result.problems.append(f"{app.company}: unknown Firm type {raw_firm!r}")

    # Programme
    raw_prog = _cell(row, cols, "Programme")
    if raw_prog and raw_prog in _PROG_BY_VALUE:
        new_prog = _PROG_BY_VALUE[raw_prog]
        if new_prog != app.programme:
            result.edits.append(ManualEdit(app.app_id, "programme", new_prog))
    elif raw_prog and raw_prog not in _PROG_BY_VALUE:
        result.problems.append(f"{app.company}: unknown Programme {raw_prog!r}")

    # Next step (free text; "None" is the placeholder for empty)
    raw_next = _cell(row, cols, "Next step")
    stored_next = app.next_step or "None"
    if raw_next and raw_next != stored_next:
        value = None if raw_next == "None" else raw_next
        result.edits.append(ManualEdit(app.app_id, "next_step", value))

    # Notes: we only detect that the free-text notes block differs; the stored
    # notes are rendered as "dd/mm: text" lines, so compare the rendered form.
    raw_notes = _cell(row, cols, "Notes")
    rendered = "\n".join(f"{n.date.strftime('%d/%m')}: {n.text}" for n in app.notes)
    if raw_notes is not None and raw_notes != rendered:
        result.edits.append(ManualEdit(app.app_id, "notes", raw_notes))


def _import_priorities(ws: object, result: ImportResult) -> None:
    rows = list(ws.iter_rows(values_only=True))  # type: ignore[attr-defined]
    if not rows:
        return
    cols = _header_index(rows[0])
    required = {"Priority", "Task", "Done?", "Source"}
    missing = required - cols.keys()
    if missing:
        result.problems.append(f"Priorities sheet missing columns: {sorted(missing)}")
        return

    for i, row in enumerate(rows[1:], start=2):
        task_text = _cell(row, cols, "Task")
        if not task_text:
            continue
        source = (_cell(row, cols, "Source") or "Auto")
        done = (_cell(row, cols, "Done?") or "No").lower() == "yes"

        if source == TaskSource.MANUAL.value:
            priority_raw = _cell(row, cols, "Priority") or Priority.MEDIUM.value
            priority = _PRIORITY_BY_VALUE.get(priority_raw, Priority.MEDIUM)
            due = row[cols["Due date"]] if "Due date" in cols else None
            result.manual_tasks.append(
                Task(
                    task_id=f"import-{i}",
                    priority=priority,
                    text=task_text,
                    company=_cell(row, cols, "Company"),
                    due=_coerce_date(due),
                    notes=_cell(row, cols, "Notes"),
                    source=TaskSource.MANUAL,
                )
            )
        elif done:
            # an Auto row marked done -> signal the matching deadline/task done
            company = _cell(row, cols, "Company")
            result.done_app_ids.append(company or task_text)


def _cell(row: tuple[object, ...], cols: dict[str, int], name: str) -> str | None:
    if name not in cols:
        return None
    value = row[cols[name]]
    if value is None:
        return None
    return str(value).strip()


def _coerce_date(value: object) -> object:
    import datetime as dt

    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return None
