import json
import os
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from agent import start_scan
from store.repository import Repository

_SFN_DEF = json.dumps({"StartAt": "x", "States": {"x": {"Type": "Pass", "End": True}}})


def _create_table(ddb: object) -> None:
    ddb.create_table(  # type: ignore[attr-defined]
        TableName="JobTracker-test",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


@pytest.fixture
def scan_env(aws_credentials: None) -> Iterator[tuple[str, Repository]]:
    with mock_aws():
        iam = boto3.client("iam", region_name="eu-north-1")
        role = iam.create_role(RoleName="sfn-role", AssumeRolePolicyDocument="{}")["Role"]["Arn"]
        sfn = boto3.client("stepfunctions", region_name="eu-north-1")
        arn = sfn.create_state_machine(name="scan", definition=_SFN_DEF, roleArn=role)[
            "stateMachineArn"
        ]
        os.environ["SCAN_WORKFLOW_ARN"] = arn
        os.environ["TABLE_NAME"] = "JobTracker-test"

        ddb = boto3.resource("dynamodb", region_name="eu-north-1")
        _create_table(ddb)
        from store import client

        client.get_repository.cache_clear()
        yield arn, Repository(ddb.Table("JobTracker-test"))


def _sqs_event(*user_ids: str) -> dict:
    return {
        "Records": [
            {"body": json.dumps({"user_id": uid, "trigger": "manual"})} for uid in user_ids
        ]
    }


def _exec_count(arn: str) -> int:
    sfn = boto3.client("stepfunctions", region_name="eu-north-1")
    return len(sfn.list_executions(stateMachineArn=arn)["executions"])


def test_starts_one_execution_per_record(scan_env: tuple[str, Repository]) -> None:
    arn, _repo = scan_env
    out = start_scan.handler(_sqs_event("u1", "u2"))
    assert out["started"] == 2
    assert _exec_count(arn) == 2


def test_empty_event_starts_nothing(scan_env: tuple[str, Repository]) -> None:
    assert start_scan.handler({"Records": []})["started"] == 0


def test_lock_prevents_second_concurrent_scan(scan_env: tuple[str, Repository]) -> None:
    arn, repo = scan_env
    # pre-acquire the lock to simulate a scan already running for u1
    import datetime as dt

    expires = int(dt.datetime.now(dt.UTC).timestamp()) + 600
    assert repo.try_acquire_scan_lock("u1", expires) is True

    out = start_scan.handler(_sqs_event("u1"))
    assert out["started"] == 0
    assert out["skipped"] == 1
    assert _exec_count(arn) == 0


def test_lock_released_allows_next_scan(scan_env: tuple[str, Repository]) -> None:
    arn, repo = scan_env
    start_scan.handler(_sqs_event("u1"))  # acquires the lock + starts
    assert _exec_count(arn) == 1
    repo.release_scan_lock("u1")
    start_scan.handler(_sqs_event("u1"))  # lock free again
    assert _exec_count(arn) == 2
