"""Excel export Lambda (Step Functions step): write the tracker to OneDrive.

Loads the user's data, builds the workbook, and writes it to OneDrive using the
import-then-overwrite flow. When the file changed since the last export, the
user's edits are read back and applied to the stored applications before the
new workbook is built (manual edits win — Requirement 6.3 / 4.6).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from excel.builder import build_workbook
from excel.importer import import_edits
from integrations.graph_onedrive import OneDriveClient, export_workbook
from store.client import get_repository
from store.repository import Repository


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    user_id = event["user_id"]
    repo = get_repository()
    user = repo.get_user(user_id)
    if user is None:
        raise ValueError(f"unknown user {user_id}")
    if not user.settings.onedrive_export:
        return {"user_id": user_id, "excel_status": "disabled"}

    client = _onedrive_client_for(user_id)
    outcome = _run_export(repo, user_id, client, user.onedrive_etag, _iso(user.last_export_at))

    if outcome.status != "locked":
        user.onedrive_etag = outcome.new_etag
        user.last_export_at = dt.datetime.now(dt.UTC)
        repo.put_user(user)

    return {"user_id": user_id, "excel_status": outcome.status}


def _run_export(
    repo: Repository,
    user_id: str,
    client: OneDriveClient,
    stored_etag: str | None,
    last_modified: str | None,
) -> Any:
    def build_bytes(imported: bytes | None) -> bytes:
        apps = repo.list_applications(user_id)
        if imported is not None:
            _apply_imported_edits(repo, user_id, imported, apps)
            apps = repo.list_applications(user_id)  # reload after edits
        deadlines = repo.list_deadlines(user_id)
        tasks = repo.list_tasks(user_id)
        scans = repo.list_scans(user_id)
        return build_workbook(apps, deadlines=deadlines, tasks=tasks, scans=scans)

    return export_workbook(
        client,
        build_bytes=build_bytes,
        last_export_modified=last_modified,
        stored_etag=stored_etag,
    )


def _apply_imported_edits(
    repo: Repository, user_id: str, xlsx_bytes: bytes, apps: list[Any]
) -> None:
    result = import_edits(xlsx_bytes, apps)
    by_id = {a.app_id: a for a in apps}
    now = dt.datetime.now(dt.UTC)
    touched: set[str] = set()
    for edit in result.edits:
        app = by_id.get(edit.app_id)
        if app is None:
            continue
        setattr(app, edit.field, edit.new_value)
        app.manual_edits[edit.field] = now  # manual edit wins until a newer email
        touched.add(edit.app_id)
    for app_id in touched:
        repo.put_application(user_id, by_id[app_id])
    # manual Priorities rows become stored tasks
    for task in result.manual_tasks:
        repo.put_task(user_id, task)


def _onedrive_client_for(user_id: str) -> OneDriveClient:
    import msal

    from integrations.graph_client import GraphClient
    from integrations.ms_config import GRAPH_SCOPES, load_config
    from integrations.secrets import ms_client_secret
    from integrations.token_crypto import decrypt_refresh_token

    repo = get_repository()
    enc = repo.get_user_secret(user_id)
    if not enc:
        raise ValueError("no stored refresh token")
    refresh_token = decrypt_refresh_token(user_id, enc)
    cfg = load_config()
    app = msal.ConfidentialClientApplication(
        client_id=cfg.client_id, authority=cfg.authority, client_credential=ms_client_secret()
    )
    _client, token = GraphClient.from_refresh_token(app, refresh_token, list(GRAPH_SCOPES))
    if token.refresh_token:
        from integrations.token_crypto import encrypt_refresh_token

        repo.put_user_secret(user_id, encrypt_refresh_token(user_id, token.refresh_token))
    return OneDriveClient(token.access_token)


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None
