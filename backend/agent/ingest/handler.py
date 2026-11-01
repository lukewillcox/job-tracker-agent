"""Ingest Lambda (Step Functions step): Graph delta sync + prefilter.

Loads the user, exchanges the KMS-encrypted refresh token for an access token,
runs :func:`agent.ingest.delta.sync_folders` over Inbox and Sent Items (saved
delta links + backfill window), and returns the prefilter-passing messages for
the classify step. Bodies live in memory only and are never persisted. The
rotated refresh token is re-encrypted and saved.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from agent.ingest.delta import DEFAULT_FOLDERS, sync_folders
from agent.ingest.prefilter import PrefilterConfig
from domain.enums import UserStatus
from integrations.graph_client import GraphClient, TokenAcquisitionError
from integrations.ms_config import GRAPH_SCOPES
from store.client import get_repository


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    user_id = event["user_id"]
    repo = get_repository()
    user = repo.get_user(user_id)
    if user is None:
        raise ValueError(f"unknown user {user_id}")

    enc = repo.get_user_secret(user_id)
    if not enc:
        raise ValueError("no stored refresh token")

    client, rotated = _graph_client_for(user_id, enc)
    if rotated is not None:
        from integrations.token_crypto import encrypt_refresh_token

        repo.put_user_secret(user_id, encrypt_refresh_token(user_id, rotated))

    is_first_scan = not user.delta_links
    backfill_start = _backfill_start(user.settings.backfill_months) if is_first_scan else None

    result = sync_folders(
        client,
        folders=DEFAULT_FOLDERS,
        saved_delta_links=user.delta_links,
        backfill_start=backfill_start,
        prefilter_config=PrefilterConfig(),
        now=dt.datetime.now(dt.UTC),
    )

    # persist the advanced delta links for the next incremental scan
    user.delta_links.update(result.delta_links)
    repo.put_user(user)

    return {
        "user_id": user_id,
        "messages": [_to_classify_input(m) for m in result.messages],
        "read_count": result.read_count,
        "passed_count": result.passed_count,
    }


def _graph_client_for(user_id: str, enc_token: str) -> tuple[GraphClient, str | None]:
    import msal

    from integrations.secrets import ms_client_secret
    from integrations.token_crypto import decrypt_refresh_token

    refresh_token = decrypt_refresh_token(user_id, enc_token)
    from integrations.ms_config import load_config

    cfg = load_config()
    app = msal.ConfidentialClientApplication(
        client_id=cfg.client_id,
        authority=cfg.authority,
        client_credential=ms_client_secret(),
    )
    try:
        client, token = GraphClient.from_refresh_token(app, refresh_token, list(GRAPH_SCOPES))
    except TokenAcquisitionError:
        _mark_needs_reconnect(user_id)
        raise
    return client, token.refresh_token


def _mark_needs_reconnect(user_id: str) -> None:
    repo = get_repository()
    user = repo.get_user(user_id)
    if user is not None:
        user.status = UserStatus.NEEDS_RECONNECT
        repo.put_user(user)


def _backfill_start(months: int) -> dt.datetime:
    now = dt.datetime.now(dt.UTC)
    return now - dt.timedelta(days=30 * months)


def _to_classify_input(m: Any) -> dict[str, Any]:
    return {
        "message_id": m.message_id,
        "internet_message_id": m.internet_message_id,
        "conversation_id": m.conversation_id,
        "subject": m.subject,
        "sender": m.sender,
        "received": m.received,
        "web_link": m.web_link,
        "body_text": m.body_text,
    }
