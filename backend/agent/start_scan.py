"""start_scan Lambda: consume the scan queue and start one workflow per user.

Enforces the per-user "only one scan at a time" rule (Requirement 7.3) with a
conditional write of a lock item, then starts the Step Functions ScanWorkflow.
Driven by the SQS scan queue (batch size 1).
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

import boto3

from store.client import get_repository

# a scan should never run longer than the Step Functions timeout (15 min);
# the lock self-expires a little after that so a crashed run can't wedge a user.
_LOCK_TTL_SECONDS = 20 * 60


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    workflow_arn = os.environ["SCAN_WORKFLOW_ARN"]
    sfn = boto3.client("stepfunctions")
    repo = get_repository()
    started = 0
    skipped = 0
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        user_id = body["user_id"]
        expires = int(dt.datetime.now(dt.UTC).timestamp()) + _LOCK_TTL_SECONDS
        if not repo.try_acquire_scan_lock(user_id, expires):
            # a scan is already running for this user (Requirement 7.3)
            skipped += 1
            continue
        try:
            sfn.start_execution(
                stateMachineArn=workflow_arn,
                input=json.dumps(
                    {"user_id": user_id, "trigger": body.get("trigger", "scheduled")}
                ),
            )
            started += 1
        except Exception:
            repo.release_scan_lock(user_id)
            raise
    return {"started": started, "skipped": skipped}
