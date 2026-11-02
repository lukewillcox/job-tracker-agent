import datetime as dt
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from classifyapi.codes import new_code, parse_code_id, verify
from classifyapi.store import CapExceededError, CodeStore


@pytest.fixture
def codes_table(aws_credentials: None) -> Iterator[object]:
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="eu-north-1")
        ddb.create_table(
            TableName="JobTrackerCodes-test",
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
        yield ddb.Table("JobTrackerCodes-test")


@pytest.fixture
def store(codes_table: object) -> CodeStore:
    return CodeStore(codes_table)  # type: ignore[arg-type]


# --- codes ---------------------------------------------------------------
def test_new_code_roundtrip_and_verify() -> None:
    code, raw = new_code("Sam")
    assert raw.startswith("jt_")
    assert parse_code_id(raw) == code.code_id
    assert verify(raw, code.code_hash) is True
    assert verify("jt_wrong_secret", code.code_hash) is False


def test_malformed_code_id() -> None:
    assert parse_code_id("garbage") is None
    assert parse_code_id("jt_only") is None


def test_put_get_code(store: CodeStore) -> None:
    code, _ = new_code("Sam")
    store.put_code(code)
    loaded = store.get_code(code.code_id)
    assert loaded is not None
    assert loaded.label == "Sam"
    assert loaded.active is True


def test_revoke_code(store: CodeStore) -> None:
    code, _ = new_code("Sam")
    store.put_code(code)
    assert store.revoke_code(code.code_id) is True
    assert store.get_code(code.code_id).active is False  # type: ignore[union-attr]
    # second revoke is a no-op
    assert store.revoke_code(code.code_id) is False


def test_list_codes(store: CodeStore) -> None:
    for name in ("Sam", "Alex", "Jo"):
        store.put_code(new_code(name)[0])
    assert len(store.list_codes()) == 3


# --- caps ----------------------------------------------------------------
def test_request_cap_enforced_atomically(store: CodeStore) -> None:
    code, _ = new_code("Sam", daily_request_cap=3)
    store.put_code(code)
    for _ in range(3):
        store.charge_request(code)  # 1,2,3 allowed
    with pytest.raises(CapExceededError):
        store.charge_request(code)  # 4th rejected
    usage = store.get_usage(code.code_id)
    assert usage.requests == 3
    assert usage.throttled == 1


def test_token_cap_blocks_further_requests(store: CodeStore) -> None:
    code, _ = new_code("Sam", daily_token_cap=1000)
    store.put_code(code)
    store.charge_request(code)
    store.record_tokens(code.code_id, input_tokens=600, output_tokens=500)  # 1100 > cap
    with pytest.raises(CapExceededError):
        store.charge_request(code)  # next request blocked by token cap


def test_usage_accumulates(store: CodeStore) -> None:
    code, _ = new_code("Sam")
    store.put_code(code)
    store.charge_request(code)
    store.record_tokens(code.code_id, 100, 20)
    store.charge_request(code)
    store.record_tokens(code.code_id, 150, 30)
    u = store.get_usage(code.code_id)
    assert u.requests == 2
    assert u.input_tokens == 250
    assert u.output_tokens == 50
    assert u.total_tokens == 300


def test_usage_isolated_per_code(store: CodeStore) -> None:
    a, _ = new_code("A")
    b, _ = new_code("B")
    store.put_code(a)
    store.put_code(b)
    store.charge_request(a)
    assert store.get_usage(a.code_id).requests == 1
    assert store.get_usage(b.code_id).requests == 0


def test_list_usage_returns_days(store: CodeStore) -> None:
    code, _ = new_code("Sam")
    store.put_code(code)
    store.charge_request(code)
    rows = store.list_usage(code.code_id)
    assert len(rows) == 1
    assert rows[0].day == dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
