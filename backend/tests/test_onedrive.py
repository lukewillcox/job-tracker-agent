from typing import Any

from integrations.graph_onedrive import (
    FileMeta,
    OneDriveClient,
    OneDriveLockedError,
    export_workbook,
)


class FakeOneDrive(OneDriveClient):
    """A scriptable OneDriveClient that records uploads."""

    def __init__(
        self,
        meta: FileMeta,
        download_bytes: bytes = b"EXISTING",
        upload_behaviour: list[str] | None = None,
    ) -> None:
        self._meta = meta
        self._download = download_bytes
        # sequence of outcomes for successive upload() calls: ok | 412 | 423
        self._behaviour = upload_behaviour or ["ok"]
        self.uploads: list[dict[str, Any]] = []
        self.downloads = 0

    def get_meta(self) -> FileMeta:
        return self._meta

    def download(self) -> bytes:
        self.downloads += 1
        return self._download

    def upload(self, data: bytes, if_match: str | None = None) -> str:
        self.uploads.append({"data": data, "if_match": if_match})
        outcome = self._behaviour.pop(0)
        if outcome == "412":
            from integrations.graph_onedrive import _PreconditionFailedError

            raise _PreconditionFailedError()
        if outcome == "423":
            raise OneDriveLockedError("locked")
        return "etag-new"


def _build(_imported: bytes | None) -> bytes:
    return b"NEWWORKBOOK"


def test_new_file_written_without_import() -> None:
    client = FakeOneDrive(FileMeta(etag=None, last_modified=None, exists=False))
    outcome = export_workbook(
        client, build_bytes=_build, last_export_modified=None, stored_etag=None
    )
    assert outcome.status == "written"
    assert client.downloads == 0  # nothing to import
    assert client.uploads[0]["data"] == b"NEWWORKBOOK"


def test_changed_file_is_imported_first() -> None:
    client = FakeOneDrive(FileMeta(etag="etag-v2", last_modified=None, exists=True))
    seen: dict[str, Any] = {}

    def build(imported: bytes | None) -> bytes:
        seen["imported"] = imported
        return b"NEW"

    outcome = export_workbook(
        client, build_bytes=build, last_export_modified=None, stored_etag="etag-v1"
    )
    assert outcome.status == "written_after_merge"
    assert seen["imported"] == b"EXISTING"  # downloaded + passed to build
    assert client.uploads[0]["if_match"] == "etag-v2"


def test_unchanged_file_not_imported() -> None:
    client = FakeOneDrive(FileMeta(etag="same", last_modified=None, exists=True))
    outcome = export_workbook(
        client, build_bytes=_build, last_export_modified=None, stored_etag="same"
    )
    assert outcome.status == "written"
    assert client.downloads == 0


def test_precondition_failed_reimports_and_retries() -> None:
    client = FakeOneDrive(
        FileMeta(etag="etag-a", last_modified=None, exists=True),
        upload_behaviour=["412", "ok"],
    )
    outcome = export_workbook(
        client, build_bytes=_build, last_export_modified=None, stored_etag="etag-a"
    )
    assert outcome.status == "written_after_merge"
    assert len(client.uploads) == 2
    assert client.uploads[1]["if_match"] is None  # retry without If-Match


def test_locked_file_reported() -> None:
    client = FakeOneDrive(
        FileMeta(etag=None, last_modified=None, exists=False),
        upload_behaviour=["423"],
    )
    outcome = export_workbook(
        client, build_bytes=_build, last_export_modified=None, stored_etag=None
    )
    assert outcome.status == "locked"
    assert outcome.new_etag is None
