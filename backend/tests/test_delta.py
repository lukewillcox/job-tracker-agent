import datetime as dt
from typing import Any

from agent.ingest.delta import DEFAULT_FOLDERS, assert_read_only, sync_folders
from agent.ingest.prefilter import PrefilterConfig


class RecordingGraph:
    """A fake GraphClient that serves canned pages and records every request."""

    def __init__(self, pages: dict[str, list[dict[str, Any]]]) -> None:
        # map from a path substring -> list of sequential page responses
        self._pages = pages
        self._cursor: dict[str, int] = {}
        self.requests: list[dict[str, Any]] = []

    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append({"method": "GET", "url": path_or_url, "params": params})
        for key, responses in self._pages.items():
            if key in path_or_url:
                i = self._cursor.get(key, 0)
                self._cursor[key] = min(i + 1, len(responses) - 1)
                return responses[i]
        return {"value": []}


def _msg(mid: str, sender: str, subject: str, imid: str, preview: str = "") -> dict[str, Any]:
    return {
        "id": mid,
        "internetMessageId": imid,
        "conversationId": f"conv-{mid}",
        "subject": subject,
        "from": {"emailAddress": {"address": sender}},
        "receivedDateTime": "2026-10-10T09:00:00Z",
        "bodyPreview": preview,
        "webLink": f"https://outlook.office.com/mail/id/{mid}",
    }


def _pages_for(folder: str, messages: list[dict], delta: str = "DELTA") -> dict:
    return {
        f"mailFolders/{folder}/messages/delta": [
            {"value": messages, "@odata.deltaLink": delta}
        ],
        "/me/messages/": [{"body": {"contentType": "text", "content": "Thanks for applying."}}],
    }


def test_prefilter_applied_only_passing_messages_fetched() -> None:
    pages = {
        "mailFolders/inbox/messages/delta": [
            {
                "value": [
                    _msg("m1", "careers@bank.com", "Your interview invitation", "i1"),
                    _msg("m2", "news@newsletter.com", "Weekly digest", "i2"),
                ],
                "@odata.deltaLink": "DELTA-INBOX",
            }
        ],
        "mailFolders/sentitems/messages/delta": [{"value": [], "@odata.deltaLink": "DELTA-SENT"}],
        "/me/messages/": [{"body": {"contentType": "text", "content": "Please attend."}}],
    }
    graph = RecordingGraph(pages)
    result = sync_folders(graph)  # type: ignore[arg-type]

    assert result.read_count == 2
    assert result.passed_count == 1
    assert [m.message_id for m in result.messages] == ["m1"]
    assert result.messages[0].body_text == "Please attend."
    assert result.delta_links == {"inbox": "DELTA-INBOX", "sentitems": "DELTA-SENT"}


def test_dedupe_skips_already_processed() -> None:
    pages = {
        "mailFolders/inbox/messages/delta": [
            {
                "value": [_msg("m1", "careers@bank.com", "assessment invite", "i1")],
                "@odata.deltaLink": "D",
            }
        ],
        "mailFolders/sentitems/messages/delta": [{"value": [], "@odata.deltaLink": "D2"}],
    }
    graph = RecordingGraph(pages)
    result = sync_folders(graph, already_processed={"i1"})  # type: ignore[arg-type]
    assert result.passed_count == 0  # already processed, not re-fetched


def test_backfill_filter_on_first_scan() -> None:
    graph = RecordingGraph({"delta": [{"value": [], "@odata.deltaLink": "D"}]})
    start = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
    sync_folders(graph, folders=("inbox",), backfill_start=start)  # type: ignore[arg-type]
    first = graph.requests[0]
    assert first["params"]["$filter"].startswith("receivedDateTime ge 2026-07-01")


def test_ingestion_never_mutates_messages() -> None:
    pages = _pages_for("inbox", [_msg("m1", "careers@bank.com", "offer", "i1")])
    pages["mailFolders/sentitems/messages/delta"] = [{"value": [], "@odata.deltaLink": "D"}]
    graph = RecordingGraph(pages)
    sync_folders(graph, folders=DEFAULT_FOLDERS)  # type: ignore[arg-type]
    # the whole point: only GETs, never a PATCH/POST/DELETE/move
    assert_read_only(graph.requests)


def test_removed_markers_skipped() -> None:
    pages = {
        "mailFolders/inbox/messages/delta": [
            {
                "value": [{"id": "m1", "@removed": {"reason": "deleted"}}],
                "@odata.deltaLink": "D",
            }
        ],
        "mailFolders/sentitems/messages/delta": [{"value": [], "@odata.deltaLink": "D2"}],
    }
    graph = RecordingGraph(pages)
    result = sync_folders(graph)  # type: ignore[arg-type]
    assert result.passed_count == 0


def test_negative_sender_config_respected() -> None:
    pages = {
        "mailFolders/inbox/messages/delta": [
            {
                "value": [_msg("m1", "spam@recruiter.com", "Available for interview?", "i1")],
                "@odata.deltaLink": "D",
            }
        ],
        "mailFolders/sentitems/messages/delta": [{"value": [], "@odata.deltaLink": "D2"}],
    }
    cfg = PrefilterConfig(negative_senders={"spam@recruiter.com"})
    graph = RecordingGraph(pages)
    result = sync_folders(graph, prefilter_config=cfg)  # type: ignore[arg-type]
    assert result.passed_count == 0
