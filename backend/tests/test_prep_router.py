import json
import os

import boto3
import pytest
from moto import mock_aws

from agent.prep import router


def _record(
    event_name: str,
    new_stage: str | None,
    old_stage: str | None,
    sk: str = "APP#a1",
) -> dict:
    dynamodb: dict = {
        "Keys": {"PK": {"S": "USER#u1"}, "SK": {"S": sk}},
    }
    if new_stage is not None:
        dynamodb["NewImage"] = {"data": {"M": {"furthest_stage": {"S": new_stage}}}}
    if old_stage is not None:
        dynamodb["OldImage"] = {"data": {"M": {"furthest_stage": {"S": old_stage}}}}
    return {"eventName": event_name, "dynamodb": dynamodb}


@pytest.fixture
def queue_url(aws_credentials: None):
    with mock_aws():
        sqs = boto3.client("sqs", region_name="eu-north-1")
        url = sqs.create_queue(QueueName="prep")["QueueUrl"]
        os.environ["PREP_QUEUE_URL"] = url
        yield url


def _count(url: str) -> int:
    sqs = boto3.client("sqs", region_name="eu-north-1")
    attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])
    return int(attrs["Attributes"]["ApproximateNumberOfMessages"])


def test_enqueues_on_transition_to_interview(queue_url: str) -> None:
    out = router.handler({"Records": [_record("MODIFY", "Interview", "Online assessment")]})
    assert out["enqueued"] == 1
    assert _count(queue_url) == 1


def test_no_enqueue_when_already_interview(queue_url: str) -> None:
    out = router.handler({"Records": [_record("MODIFY", "Final round", "Interview")]})
    assert out["enqueued"] == 0


def test_no_enqueue_below_interview(queue_url: str) -> None:
    out = router.handler({"Records": [_record("INSERT", "Online assessment", None)]})
    assert out["enqueued"] == 0


def test_new_application_straight_to_interview_enqueues(queue_url: str) -> None:
    out = router.handler({"Records": [_record("INSERT", "Interview", None)]})
    assert out["enqueued"] == 1


def test_ignores_non_application_items(queue_url: str) -> None:
    out = router.handler({"Records": [_record("MODIFY", "Interview", None, sk="DEADLINE#d1")]})
    assert out["enqueued"] == 0


def test_message_body_carries_keys(queue_url: str) -> None:
    router.handler({"Records": [_record("INSERT", "Interview", None)]})
    sqs = boto3.client("sqs", region_name="eu-north-1")
    msg = sqs.receive_message(QueueUrl=queue_url)["Messages"][0]
    body = json.loads(msg["Body"])
    assert body == {"pk": "USER#u1", "sk": "APP#a1"}
