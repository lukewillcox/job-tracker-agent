import datetime as dt
from typing import Any

from agent.ingest.delta import DEFAULT_FOLDERS, assert_read_only, sync_folders
from agent.ingest.prefilter import PrefilterConfig


class RoutingGraph:
    """Fake GraphClient routed by a predicate over (url, params); records calls.

    First-scan flow per folder now hits two endpoints:
      - GET /me/mailFolders/{f}/messages           (backfill, supports $filter)
      - GET /me/mailFolders/{f}/messages/delta?$deltatoken=latest   (prime cursor)
    Incremental flow follows a saved deltaLink.
    Full-body fetch: GET /me/messages/{id}?$select=body
    """

    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self.requests: list[dict[str, Any]] = []

    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append({"method": "GET", "url": path_or_url, "params": params})
        return self._handler(path_or_url, params)


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


def _is_delta(url: str) -> bool:
    return "/messages/delta" in url


def _is_backfill(url: str) -> bool:
    return url.endswith("/messages") or "/messages?" in url


def _is_body(url: str) -> bool:
    return "/me/messages/" in url and "/delta" not in url


def _folder(url: str) -> str:
    for f in ("inbox", "sentitems"):
        if f in url:
            return f
    return "?"


def make_handler(backfill: dict[str, list[dict]], body: str = "Body text.") -> Any:
    """backfill: {folder -> list of message dicts} for the first-scan backfill."""

    def handler(url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        if _is_body(url):
            return {"body": {"contentType": "text", "content": body}}
        if _is_delta(url):
            # priming call: empty value + a deltaLink per folder
            return {"value": [], "@odata.deltaLink": f"DELTA-{_folder(url)}"}
        if _is_backfill(url):
            return {"value": backfill.get(_folder(url), [])}
        return {"value": []}

    return handler


def test_prefilter_applied_only_passing_messages_fetched() -> None:
    graph = RoutingGraph(
        make_handler(
            {
                "inbox": [
                    _msg("m1", "careers@bank.com", "Your interview invitation", "i1"),
                    _msg("m2", "news@newsletter.com", "Weekly digest", "i2"),
                ],
                "sentitems": [],
            },
            body="Please attend.",
        )
    )
    result = sync_folders(graph)  # type: ignore[arg-type]
    assert result.read_count == 2
    assert result.passed_count == 1
    assert [m.message_id for m in result.messages] == ["m1"]
    assert result.messages[0].body_text == "Please attend."
    # delta links primed for the next incremental scan
    assert result.delta_links == {"inbox": "DELTA-inbox", "sentitems": "DELTA-sentitems"}


def test_dedupe_skips_already_processed() -> None:
    graph = RoutingGraph(
        make_handler({"inbox": [_msg("m1", "careers@bank.com", "assessment invite", "i1")]})
    )
    result = sync_folders(graph, already_processed={"i1"})  # type: ignore[arg-type]
    assert result.passed_count == 0


def test_backfill_uses_messages_endpoint_with_filter_not_delta() -> None:
    graph = RoutingGraph(make_handler({"inbox": []}))
    start = dt.datetime(2026, 7, 1, tzinfo=dt.UTC)
    sync_folders(graph, folders=("inbox",), backfill_start=start)  # type: ignore[arg-type]
    # the first request is the backfill /messages call carrying the $filter
    first = graph.requests[0]
    assert first["url"].endswith("/me/mailFolders/inbox/messages")
    assert first["params"]["$filter"].startswith("receivedDateTime ge 2026-07-01")
    assert "$orderby" in first["params"]
    # a delta-prime call is made afterwards (no $filter on it)
    assert any(_is_delta(r["url"]) for r in graph.requests)


def test_incremental_scan_follows_saved_deltalink() -> None:
    def handler(url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        if _is_body(url):
            return {"body": {"contentType": "text", "content": "Attend."}}
        if "SAVED-DELTA" in url:
            return {
                "value": [_msg("m9", "careers@bank.com", "offer", "i9")],
                "@odata.deltaLink": "NEW-DELTA",
            }
        return {"value": []}

    graph = RoutingGraph(handler)
    result = sync_folders(
        graph, folders=("inbox",), saved_delta_links={"inbox": "https://graph/SAVED-DELTA"}
    )  # type: ignore[arg-type]
    assert result.passed_count == 1
    assert result.delta_links["inbox"] == "NEW-DELTA"
    # it did NOT hit the backfill /messages endpoint
    assert not any(_is_backfill(r["url"]) for r in graph.requests)


def test_ingestion_never_mutates_messages() -> None:
    graph = RoutingGraph(
        make_handler({"inbox": [_msg("m1", "careers@bank.com", "offer", "i1")], "sentitems": []})
    )
    sync_folders(graph, folders=DEFAULT_FOLDERS)  # type: ignore[arg-type]
    assert_read_only(graph.requests)


def test_negative_sender_config_respected() -> None:
    spam = _msg("m1", "spam@recruiter.com", "Available for interview?", "i1")
    graph = RoutingGraph(make_handler({"inbox": [spam]}))
    cfg = PrefilterConfig(negative_senders={"spam@recruiter.com"})
    result = sync_folders(graph, folders=("inbox",), prefilter_config=cfg)  # type: ignore[arg-type]
    assert result.passed_count == 0


def test_body_fetch_failure_falls_back_to_preview() -> None:
    """A Graph 502 on one message's body must not abort the whole scan."""

    import requests

    ok = make_handler(
        {"inbox": [_msg("m1", "careers@bank.com", "Your interview invitation", "i1",
                        preview="Please book your interview slot.")], "sentitems": []}
    )

    def handler(url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        if _is_body(url):
            raise requests.HTTPError("502 Server Error: Bad Gateway")
        return ok(url, params)  # type: ignore[no-any-return]

    result = sync_folders(RoutingGraph(handler))  # type: ignore[arg-type]
    assert [m.message_id for m in result.messages] == ["m1"]
    assert "book your interview" in result.messages[0].body_text
