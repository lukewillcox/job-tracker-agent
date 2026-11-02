"""OneDrive read/write for the Excel tracker (Task 8, design.md "OneDrive").

The tracker lives at ``Job Search/Job_Applications_Tracker.xlsx`` in the user's
OneDrive. Write flow:

  1. GET the file metadata (lastModifiedDateTime + eTag).
  2. If it changed since our last export, download it and return the bytes so
     the caller can import the user's edits first.
  3. Upload with ``PUT .../content`` and ``If-Match: {eTag}``.
     - 412 (changed meanwhile): re-download for a fresh import, retry once.
     - 423 (locked): signal the caller to retry later.

Graph calls go through :class:`GraphClient` for a single bearer token; the
upload/download verbs that the read-only ``GraphClient.get`` does not cover are
issued here with explicit methods, so they are intentionally the only mutating
Graph calls in the app (and they touch only this one app-owned file).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import requests

from integrations.graph_client import GRAPH_BASE

TRACKER_PATH = "Job Search/Job_Applications_Tracker.xlsx"
_ITEM_URL = f"{GRAPH_BASE}/me/drive/root:/{TRACKER_PATH}"
_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class OneDriveLockedError(RuntimeError):
    """The target file is locked (HTTP 423); retry later."""


@dataclass
class FileMeta:
    etag: str | None
    last_modified: str | None
    exists: bool


class OneDriveClient:
    def __init__(self, access_token: str, session: requests.Session | None = None) -> None:
        self._token = access_token
        self._session = session or requests.Session()

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._token}"}
        if extra:
            h.update(extra)
        return h

    def get_meta(self) -> FileMeta:
        resp = self._session.get(_ITEM_URL, headers=self._headers(), timeout=30)
        if resp.status_code == 404:
            return FileMeta(etag=None, last_modified=None, exists=False)
        resp.raise_for_status()
        body = resp.json()
        return FileMeta(
            etag=body.get("eTag"),
            last_modified=body.get("lastModifiedDateTime"),
            exists=True,
        )

    def download(self) -> bytes:
        resp = self._session.get(
            f"{_ITEM_URL}:/content", headers=self._headers(), timeout=60
        )
        resp.raise_for_status()
        return resp.content

    def upload(self, data: bytes, if_match: str | None = None) -> str:
        """Upload the workbook; return the new eTag. Raises on 412/423."""

        headers = self._headers({"Content-Type": _XLSX_CT})
        if if_match:
            headers["If-Match"] = if_match
        resp = self._session.put(
            f"{_ITEM_URL}:/content", headers=headers, data=data, timeout=120
        )
        if resp.status_code == 412:
            raise _PreconditionFailedError()
        if resp.status_code == 423:
            raise OneDriveLockedError("OneDrive file is locked")
        resp.raise_for_status()
        new_etag = resp.json().get("eTag")
        return str(new_etag) if new_etag else ""


class _PreconditionFailedError(RuntimeError):
    """Internal: If-Match failed (412); the caller re-imports and retries once."""


@dataclass
class ExportOutcome:
    status: str  # "written" | "written_after_merge" | "locked"
    new_etag: str | None
    imported_bytes: bytes | None  # file content to import edits from, if any


def export_workbook(
    client: OneDriveClient,
    *,
    build_bytes: BuildFn,
    last_export_modified: str | None,
    stored_etag: str | None,
) -> ExportOutcome:
    """Write the tracker, importing user edits first when the file changed.

    ``build_bytes`` is a callable that returns the workbook bytes to upload,
    given optional "imported" bytes to merge from. Keeping it a callback lets
    the caller own the build/import so this module stays Graph-only.
    """

    meta = client.get_meta()
    imported: bytes | None = None
    if meta.exists and _changed_since(meta, last_export_modified, stored_etag):
        imported = client.download()

    data = build_bytes(imported)
    try:
        new_etag = client.upload(data, if_match=meta.etag)
        return ExportOutcome(
            "written_after_merge" if imported else "written", new_etag, imported
        )
    except _PreconditionFailedError:
        # changed between our GET and PUT: re-download, rebuild, retry once
        fresh = client.download()
        data = build_bytes(fresh)
        new_etag = client.upload(data)  # no If-Match on the retry
        return ExportOutcome("written_after_merge", new_etag, fresh)
    except OneDriveLockedError:
        return ExportOutcome("locked", meta.etag, None)


def _changed_since(meta: FileMeta, last_modified: str | None, stored_etag: str | None) -> bool:
    if stored_etag is not None and meta.etag is not None:
        return meta.etag != stored_etag
    if last_modified is not None and meta.last_modified is not None:
        return meta.last_modified > last_modified
    # unknown baseline: be safe and import before overwriting
    return True


BuildFn = Callable[[bytes | None], bytes]
