from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from classifyapi import admin
from classifyapi.billing import beers, cost_gbp
from classifyapi.store import CodeStore


@pytest.fixture
def codes_env(aws_credentials: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[CodeStore]:
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="eu-north-1")
        ddb.create_table(
            TableName="JobTrackerCodes-dev",
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
        monkeypatch.setenv("CODES_TABLE", "JobTrackerCodes-dev")
        monkeypatch.setenv("AWS_REGION", "eu-north-1")
        yield CodeStore(ddb.Table("JobTrackerCodes-dev"))


def test_cost_and_beers() -> None:
    # 1M input + 1M output at default prices (1 + 5 USD) * 0.79 = ~4.74 GBP
    gbp = cost_gbp(1_000_000, 1_000_000)
    assert 4.0 < gbp < 5.5
    assert beers(gbp) == round(gbp / 6.50, 1)


def test_add_creates_user_and_prints_code(
    codes_env: CodeStore, capsys: pytest.CaptureFixture
) -> None:
    rc = admin.main(["add", "Sam"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "jt_sam_" in out  # one-time code printed
    assert codes_env.get_code("sam") is not None


def test_add_duplicate_fails(codes_env: CodeStore) -> None:
    assert admin.main(["add", "Sam"]) == 0
    assert admin.main(["add", "sam"]) == 1  # same normalised username


def test_disable(codes_env: CodeStore) -> None:
    admin.main(["add", "Sam"])
    assert admin.main(["disable", "Sam"]) == 0
    assert codes_env.get_code("sam").active is False  # type: ignore[union-attr]
    assert admin.main(["disable", "Sam"]) == 1  # already off


def test_users_table_with_total(
    codes_env: CodeStore, capsys: pytest.CaptureFixture
) -> None:
    admin.main(["add", "Sam"])
    admin.main(["add", "Alex"])
    # simulate some usage for Sam
    sam = codes_env.get_code("sam")
    assert sam is not None
    codes_env.charge_request(sam)
    codes_env.record_tokens("sam", 1000, 200)
    capsys.readouterr()  # clear

    rc = admin.main(["users"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sam" in out and "alex" in out
    assert "TOTAL" in out
    assert "pints" in out
