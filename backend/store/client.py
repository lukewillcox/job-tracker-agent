"""Construct a :class:`Repository` bound to the configured table."""

from __future__ import annotations

import os
from functools import lru_cache

import boto3

from store.repository import Repository


@lru_cache(maxsize=1)
def get_repository() -> Repository:
    """Return a process-cached repository for the ``TABLE_NAME`` env table."""

    table_name = os.environ["TABLE_NAME"]
    table = boto3.resource("dynamodb").Table(table_name)
    return Repository(table)
