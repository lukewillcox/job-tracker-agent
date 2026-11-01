"""Excel export Lambda (Step Functions step): write the tracker to OneDrive.

Reads the user's applications/deadlines/tasks/scans from the repository, builds
the workbook with the implemented, tested :func:`excel.builder.build_workbook`,
and writes it to the user's OneDrive with the eTag import-then-overwrite flow.
If the file changed since the last export, edits are first read back with the
implemented :func:`excel.importer.import_edits`.

The OneDrive client (`integrations.graph_onedrive`) is not implemented yet
because it needs live Microsoft Graph access; this documents the contract.
"""

from __future__ import annotations

from typing import Any


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    _user_id = event["user_id"]
    raise NotImplementedError(
        "integrations.graph_onedrive (OneDrive read/write) is not implemented yet; "
        "the workbook builder and edit importer are implemented and tested in excel/."
    )
