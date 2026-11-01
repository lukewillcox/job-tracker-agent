"""DynamoDB-stream router: enqueue prep-pack generation.

Fires on the table stream. When an application's furthest stage transitions to
Interview or later (and no prep pack exists yet), it enqueues the app on the
prep queue. Filtering the stream here keeps the prep Lambda simple and bounded.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

from domain.enums import FurthestStage, stage_rank

_INTERVIEW_RANK = stage_rank(FurthestStage.INTERVIEW)


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    queue_url = os.environ["PREP_QUEUE_URL"]
    sqs = boto3.client("sqs")
    enqueued = 0
    for record in event.get("Records", []):
        if record.get("eventName") not in ("INSERT", "MODIFY"):
            continue
        new_stage = _stage(record, "NewImage")
        old_stage = _stage(record, "OldImage")
        if not _reached_interview(new_stage) or _reached_interview(old_stage):
            continue  # only the transition into Interview matters
        pk = record["dynamodb"]["Keys"]["PK"]["S"]
        sk = record["dynamodb"]["Keys"]["SK"]["S"]
        if not sk.startswith("APP#"):
            continue
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"pk": pk, "sk": sk}),
        )
        enqueued += 1
    return {"enqueued": enqueued}


def _stage(record: dict[str, Any], image: str) -> str | None:
    """Extract ``furthest_stage`` from a stream image in DynamoDB JSON form.

    The entity JSON is stored under the ``data`` map attribute, so the image
    looks like ``{"data": {"M": {"furthest_stage": {"S": "Interview"}, ...}}}``.
    """

    img = record.get("dynamodb", {}).get(image)
    if not img:
        return None
    data = img.get("data", {}).get("M")
    if not data:
        return None
    field = data.get("furthest_stage")
    if not field:
        return None
    value = field.get("S")
    return value if isinstance(value, str) else None


def _reached_interview(stage: str | None) -> bool:
    if not stage:
        return False
    try:
        return stage_rank(FurthestStage(stage)) >= _INTERVIEW_RANK
    except ValueError:
        return False
