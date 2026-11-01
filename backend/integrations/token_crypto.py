"""Encrypt/decrypt Microsoft refresh tokens with the customer-managed KMS key.

The ``user_id`` is bound into the KMS encryption context so a ciphertext
encrypted for one user cannot be decrypted in another user's context
(defence in depth on top of the key policy). Values are returned/accepted as
base64 strings for safe storage in DynamoDB.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache

import boto3


@lru_cache(maxsize=1)
def _kms() -> object:
    return boto3.client("kms")


def _key_id() -> str:
    return os.environ["TOKEN_KEY_ARN"]


def encrypt_refresh_token(user_id: str, refresh_token: str) -> str:
    resp = _kms().encrypt(  # type: ignore[attr-defined]
        KeyId=_key_id(),
        Plaintext=refresh_token.encode("utf-8"),
        EncryptionContext={"user_id": user_id},
    )
    return base64.b64encode(resp["CiphertextBlob"]).decode("ascii")


def decrypt_refresh_token(user_id: str, ciphertext_b64: str) -> str:
    resp = _kms().decrypt(  # type: ignore[attr-defined]
        CiphertextBlob=base64.b64decode(ciphertext_b64),
        EncryptionContext={"user_id": user_id},
    )
    plaintext: bytes = resp["Plaintext"]
    return plaintext.decode("utf-8")
