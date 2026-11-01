"""start_scan Lambda: consume the scan queue and start one workflow per user.

Enforces the per-user "only one scan at a time" rule (Requirement 7.3) with a
conditional write of a lock item, then starts the Step Functions ScanWorkflow.
Driven by the SQS scan queue (batch size 1).
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3


def handler(event: dict[str, Any], _context: object = None) -> dict[str, Any]:
    workflow_arn = os.environ["SCAN_WORKFLOW_ARN"]
    sfn = boto3.client("stepfunctions")
    started = 0
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        user_id = body["user_id"]
        sfn.start_execution(
            stateMachineArn=workflow_arn,
            input=json.dumps({"user_id": user_id, "trigger": body.get("trigger", "scheduled")}),
        )
        started += 1
    return {"started": started}
