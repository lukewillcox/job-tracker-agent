"""Amazon SES email sending (Task 9 scan report, reminders).

A thin wrapper over the SESv2 ``send_email`` call. The sending identity is the
app's own address/domain (``SES_FROM``), never the user's mailbox (product
principle: read-only on email).

In the SES sandbox you can only send to verified addresses; a send to an
unverified recipient raises. Callers decide whether to treat that as fatal; the
notify handler logs and continues (a no-op) so a scan is never failed by email.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import boto3


@lru_cache(maxsize=1)
def _client() -> Any:
    return boto3.client("sesv2")


def send_email(to_address: str, subject: str, text_body: str) -> str:
    """Send a plain-text email; returns the SES MessageId."""

    from_address = os.environ["SES_FROM"]
    resp = _client().send_email(
        FromEmailAddress=from_address,
        Destination={"ToAddresses": [to_address]},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": text_body, "Charset": "UTF-8"}},
            }
        },
    )
    return str(resp.get("MessageId", ""))
