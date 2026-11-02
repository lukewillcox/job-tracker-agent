import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from integrations import token_crypto


@pytest.fixture
def kms_key(aws_credentials: None):
    with mock_aws():
        kms = boto3.client("kms", region_name="eu-north-1")
        key_id = kms.create_key(Description="test token key")["KeyMetadata"]["Arn"]
        import os

        os.environ["TOKEN_KEY_ARN"] = key_id
        token_crypto._kms.cache_clear()
        yield key_id


def test_encrypt_decrypt_roundtrip(kms_key: str) -> None:
    ct = token_crypto.encrypt_refresh_token("user-1", "RT-secret")
    assert ct != "RT-secret"
    pt = token_crypto.decrypt_refresh_token("user-1", ct)
    assert pt == "RT-secret"


def test_decrypt_wrong_user_context_fails(kms_key: str) -> None:
    ct = token_crypto.encrypt_refresh_token("user-1", "RT-secret")
    # encryption context is bound to the user; another user's context must fail
    with pytest.raises(ClientError):
        token_crypto.decrypt_refresh_token("user-2", ct)
