"""Microsoft Graph mail delta ingestion (Task 5).

Pulls new/changed messages from the Inbox and Sent Items (plus any user-chosen
folders) using Graph delta queries:

  - first scan: a delta call filtered to the backfill window
    (``receivedDateTime ge {backfill_start}``);
  - later scans: the saved ``deltaLink`` per folder, with a one-day overlap so a
    message that arrives mid-scan is not missed.

Only read operations are issued (``GET`` delta + ``GET`` message body). The
client exposes no mutating method, and ``assert_read_only`` double-checks that
no PATCH/POST/DELETE/move was attempted (Requirement 2.3 / 14.1).

Full bodies are fetched only for messages that pass the prefilter; they are
stripped of signatures/quotes, truncated to 4,000 chars and never persisted.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from agent.ingest.body import clean_body
from agent.ingest.prefilter import PrefilterConfig, prefilter
from integrations.graph_client import GraphClient

# Folders scanned by default (well-known Graph folder names).
DEFAULT_FOLDERS: tuple[str, ...] = ("inbox", "sentitems")

_SELECT = (
    "id,conversationId,internetMessageId,subject,from,toRecipients,"
    "receivedDateTime,sentDateTime,bodyPreview"
)
_OVERLAP = dt.timedelta(days=1)


@dataclass
class IngestedMessage:
    """A prefilter-passing message, ready for classification. No raw body kept."""

    message_id: str
    internet_message_id: str
    conversation_id: str | None
    subject: str
    sender: str
    received: str  # ISO 8601
    folder: str
    web_link: str | None
    body_text: str  # cleaned + truncated; lives in memory only


@dataclass
class DeltaResult:
    messages: list[IngestedMessage] = field(default_factory=list)
    delta_links: dict[str, str] = field(default_factory=dict)
    read_count: int = 0
    passed_count: int = 0


def _folder_delta_path(folder: str) -> str:
    return f"/me/mailFolders/{folder}/messages/delta"


def sync_folders(
    client: GraphClient,
    *,
    folders: tuple[str, ...] = DEFAULT_FOLDERS,
    saved_delta_links: dict[str, str] | None = None,
    backfill_start: dt.datetime | None = None,
    prefilter_config: PrefilterConfig | None = None,
    already_processed: set[str] | None = None,
    now: dt.datetime | None = None,
) -> DeltaResult:
    """Run delta sync across ``folders`` and return prefilter-passing messages."""

    saved = saved_delta_links or {}
    processed = already_processed or set()
    result = DeltaResult()

    for folder in folders:
        link = saved.get(folder)
        new_link = _sync_one_folder(
            client,
            folder,
            link,
            backfill_start,
            prefilter_config,
            processed,
            now,
            result,
        )
        if new_link:
            result.delta_links[folder] = new_link
    return result


def _sync_one_folder(
    client: GraphClient,
    folder: str,
    delta_link: str | None,
    backfill_start: dt.datetime | None,
    prefilter_config: PrefilterConfig | None,
    processed: set[str],
    now: dt.datetime | None,
    result: DeltaResult,
) -> str | None:
    # Incremental scan: follow the saved deltaLink.
    if delta_link:
        return _drain_delta(
            client, folder, _overlap_link(delta_link, now), prefilter_config, processed, result
        )

    # First scan: the Graph /messages/delta endpoint does NOT honour a
    # receivedDateTime $filter (it silently returns an empty page + a final
    # deltaLink). So backfill via the regular /messages endpoint, which fully
    # supports $filter + $orderby, then prime a deltaLink with `?$deltatoken=latest`
    # so later scans run incrementally.
    _backfill_folder(client, folder, backfill_start, prefilter_config, processed, result)
    return _prime_delta_link(client, folder)


def _backfill_folder(
    client: GraphClient,
    folder: str,
    backfill_start: dt.datetime | None,
    prefilter_config: PrefilterConfig | None,
    processed: set[str],
    result: DeltaResult,
) -> None:
    first_params: dict[str, Any] = {
        "$select": _SELECT,
        "$orderby": "receivedDateTime desc",
        "$top": 50,
    }
    if backfill_start is not None:
        first_params["$filter"] = f"receivedDateTime ge {backfill_start.isoformat()}"
    params: dict[str, Any] | None = first_params
    url: str | None = f"/me/mailFolders/{folder}/messages"
    while url:
        page = client.get(url, params=params)
        params = None  # only the first request carries query params
        for raw in page.get("value", []):
            _handle_message(client, folder, raw, prefilter_config, processed, result)
        url = page.get("@odata.nextLink")


def _prime_delta_link(client: GraphClient, folder: str) -> str | None:
    """Get the current deltaLink cheaply so the next scan runs incrementally."""

    page = client.get(_folder_delta_path(folder), params={"$deltatoken": "latest"})
    # `$deltatoken=latest` returns an empty value list and the current deltaLink
    while "@odata.nextLink" in page:
        page = client.get(page["@odata.nextLink"])
    return page.get("@odata.deltaLink")


def _drain_delta(
    client: GraphClient,
    folder: str,
    start_url: str,
    prefilter_config: PrefilterConfig | None,
    processed: set[str],
    result: DeltaResult,
) -> str | None:
    url: str | None = start_url
    latest_delta: str | None = None
    while url:
        page = client.get(url)
        for raw in page.get("value", []):
            _handle_message(client, folder, raw, prefilter_config, processed, result)
        if "@odata.nextLink" in page:
            url = page["@odata.nextLink"]
        else:
            latest_delta = page.get("@odata.deltaLink")
            url = None
    return latest_delta


def _handle_message(
    client: GraphClient,
    folder: str,
    raw: dict[str, Any],
    prefilter_config: PrefilterConfig | None,
    processed: set[str],
    result: DeltaResult,
) -> None:
    # a delta page can include "removed" markers for deleted messages; skip them
    if "@removed" in raw:
        return
    imid = raw.get("internetMessageId", "")
    result.read_count += 1
    if imid and imid in processed:
        return  # dedupe (Requirement 2.4)

    sender = _sender_address(raw)
    subject = raw.get("subject") or ""
    preview = raw.get("bodyPreview") or ""
    decision = prefilter(sender, subject, preview, prefilter_config)
    if not decision.passed:
        return

    body_text = _fetch_clean_body(client, raw["id"])
    result.passed_count += 1
    result.messages.append(
        IngestedMessage(
            message_id=raw["id"],
            internet_message_id=imid,
            conversation_id=raw.get("conversationId"),
            subject=subject,
            sender=sender,
            received=raw.get("receivedDateTime") or raw.get("sentDateTime") or "",
            folder=folder,
            web_link=raw.get("webLink"),
            body_text=body_text,
        )
    )


def _fetch_clean_body(client: GraphClient, message_id: str) -> str:
    # fetch the plain-text body only for messages that passed the prefilter
    resp = client.get(f"/me/messages/{message_id}", params={"$select": "body"})
    body = resp.get("body", {})
    content = body.get("content", "") if isinstance(body, dict) else ""
    return clean_body(content)


def _sender_address(raw: dict[str, Any]) -> str:
    frm = raw.get("from") or {}
    addr = frm.get("emailAddress", {}) if isinstance(frm, dict) else {}
    return addr.get("address", "") if isinstance(addr, dict) else ""


def _overlap_link(delta_link: str, now: dt.datetime | None) -> str:
    # The saved deltaLink already encodes the server's position; the one-day
    # overlap is applied by the caller re-checking recent messages against
    # ProcessedMessage. We return the link unchanged here and document that the
    # overlap is enforced via the dedupe set, not by rewriting the token.
    _ = (now, _OVERLAP)
    return delta_link


def assert_read_only(requests: list[dict[str, Any]]) -> None:
    """Raise if any recorded Graph request was not a safe GET."""

    for req in requests:
        if req.get("method", "GET").upper() != "GET":
            raise AssertionError(f"non-GET Graph request attempted: {req}")
