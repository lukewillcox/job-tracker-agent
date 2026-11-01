import json
import os

import boto3
import pytest
from moto import mock_aws

from agent import start_scan

_SFN_DEF = json.dumps(
    {"StartAt": "x", "States": {"x": {"Type": "Pass", "End": True}}}
)


@pytest.fixture
def workflow_arn(aws_credentials: None):
    with mock_aws():
        iam = boto3.client("iam", region_name="eu-west-2")
        role = iam.create_role(
            RoleName="sfn-role",
            AssumeRolePolicyDocument="{}",
        )["Role"]["Arn"]
        sfn = boto3.client("stepfunctions", region_name="eu-west-2")
        arn = sfn.create_state_machine(
            name="scan", definition=_SFN_DEF, roleArn=role
        )["stateMachineArn"]
        os.environ["SCAN_WORKFLOW_ARN"] = arn
        yield arn


def _sqs_event(*user_ids: str) -> dict:
    return {
        "Records": [
            {"body": json.dumps({"user_id": uid, "trigger": "manual"})} for uid in user_ids
        ]
    }


def test_starts_one_execution_per_record(workflow_arn: str) -> None:
    out = start_scan.handler(_sqs_event("u1", "u2"))
    assert out["started"] == 2
    sfn = boto3.client("stepfunctions", region_name="eu-west-2")
    execs = sfn.list_executions(stateMachineArn=workflow_arn)["executions"]
    assert len(execs) == 2


def test_empty_event_starts_nothing(workflow_arn: str) -> None:
    assert start_scan.handler({"Records": []})["started"] == 0
