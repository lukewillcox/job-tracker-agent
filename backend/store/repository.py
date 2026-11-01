"""DynamoDB single-table repository.

Every method takes a ``user_id`` so tenant isolation is enforced at the data
layer: a handler can only ever read or write within its own ``USER#{uid}``
partition (Requirement 14.7). Entities are stored as their Pydantic JSON under a
``data`` attribute, with the key attributes (and GSI keys where needed) promoted
to top level for querying.

The float/Decimal and datetime concerns of the DynamoDB wire format are handled
by serialising through Pydantic's JSON mode, so stored items contain only
strings, ints, bools and nested maps/lists.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from domain.enums import UserStatus
from domain.models import (
    Application,
    Deadline,
    Event,
    PrepPack,
    ScanRun,
    Task,
    User,
)
from store.keys import K

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

_DATA = "data"


def _dump(model: BaseModel) -> dict[str, Any]:
    """Pydantic model -> DynamoDB-safe dict.

    Serialising through Pydantic JSON mode turns datetimes/enums into strings;
    parsing back with ``parse_float=Decimal`` turns floats (e.g. confidence,
    est_cost) into ``Decimal`` as DynamoDB requires.
    """

    result: dict[str, Any] = json.loads(model.model_dump_json(), parse_float=Decimal)
    return result


def _load[M: BaseModel](model_cls: type[M], item: dict[str, Any]) -> M:
    return model_cls.model_validate(item[_DATA])


class Repository:
    """Typed access to the JobTracker single table."""

    def __init__(self, table: Table) -> None:
        self._t = table

    # --- users -----------------------------------------------------------
    def put_user(self, user: User) -> None:
        self._t.put_item(
            Item={
                "PK": K.user_pk(user.user_id),
                "SK": K.PROFILE,
                # GSI2: only active users are listed for ops/scheduling
                **(
                    {"GSI2PK": K.ACTIVE_USERS_PK, "GSI2SK": K.active_user_sk(user.user_id)}
                    if user.status == UserStatus.ACTIVE
                    else {}
                ),
                _DATA: _dump(user),
            }
        )

    def get_user(self, user_id: str) -> User | None:
        resp = self._t.get_item(Key={"PK": K.user_pk(user_id), "SK": K.PROFILE})
        item = resp.get("Item")
        return _load(User, item) if item else None

    # --- applications ----------------------------------------------------
    def put_application(self, user_id: str, app: Application) -> None:
        self._t.put_item(
            Item={
                "PK": K.user_pk(user_id),
                "SK": K.app_sk(app.app_id),
                _DATA: _dump(app),
            }
        )

    def get_application(self, user_id: str, app_id: str) -> Application | None:
        resp = self._t.get_item(Key={"PK": K.user_pk(user_id), "SK": K.app_sk(app_id)})
        item = resp.get("Item")
        return _load(Application, item) if item else None

    def list_applications(self, user_id: str, include_deleted: bool = False) -> list[Application]:
        items = self._query_prefix(user_id, K.APP_PREFIX)
        apps = [_load(Application, i) for i in items]
        if not include_deleted:
            apps = [a for a in apps if a.deleted_at is None]
        return apps

    # --- events ----------------------------------------------------------
    def put_event(self, user_id: str, event: Event) -> None:
        ts = event.email_date.isoformat()
        self._t.put_item(
            Item={
                "PK": K.user_pk(user_id),
                "SK": K.event_sk(event.app_id, ts, event.message_id),
                _DATA: _dump(event),
            }
        )

    def list_events(self, user_id: str, app_id: str) -> list[Event]:
        items = self._query_prefix(user_id, K.event_prefix(app_id))
        return [_load(Event, i) for i in items]

    # --- processed-message dedupe ---------------------------------------
    def mark_processed(
        self, user_id: str, internet_message_id: str, outcome: str, ttl: int
    ) -> None:
        self._t.put_item(
            Item={
                "PK": K.user_pk(user_id),
                "SK": K.msg_sk(internet_message_id),
                "outcome": outcome,
                "ttl": ttl,
            }
        )

    def is_processed(self, user_id: str, internet_message_id: str) -> bool:
        resp = self._t.get_item(
            Key={"PK": K.user_pk(user_id), "SK": K.msg_sk(internet_message_id)}
        )
        return "Item" in resp

    # --- deadlines -------------------------------------------------------
    def put_deadline(self, user_id: str, deadline: Deadline) -> None:
        self._t.put_item(
            Item={
                "PK": K.user_pk(user_id),
                "SK": K.deadline_sk(deadline.deadline_id),
                _DATA: _dump(deadline),
            }
        )

    def list_deadlines(self, user_id: str) -> list[Deadline]:
        items = self._query_prefix(user_id, K.DEADLINE_PREFIX)
        return [_load(Deadline, i) for i in items]

    # --- tasks (Priorities manual rows) ----------------------------------
    def put_task(self, user_id: str, task: Task) -> None:
        self._t.put_item(
            Item={
                "PK": K.user_pk(user_id),
                "SK": K.task_sk(task.task_id),
                _DATA: _dump(task),
            }
        )

    def list_tasks(self, user_id: str) -> list[Task]:
        items = self._query_prefix(user_id, K.TASK_PREFIX)
        return [_load(Task, i) for i in items]

    # --- scan runs -------------------------------------------------------
    def put_scan(self, user_id: str, scan: ScanRun) -> None:
        self._t.put_item(
            Item={
                "PK": K.user_pk(user_id),
                "SK": K.scan_sk(scan.started_at.isoformat()),
                _DATA: _dump(scan),
            }
        )

    def list_scans(self, user_id: str) -> list[ScanRun]:
        items = self._query_prefix(user_id, K.SCAN_PREFIX)
        return [_load(ScanRun, i) for i in items]

    # --- prep packs ------------------------------------------------------
    def put_prep(self, user_id: str, prep: PrepPack) -> None:
        self._t.put_item(
            Item={
                "PK": K.user_pk(user_id),
                "SK": K.prep_sk(prep.app_id),
                _DATA: _dump(prep),
            }
        )

    def get_prep(self, user_id: str, app_id: str) -> PrepPack | None:
        resp = self._t.get_item(Key={"PK": K.user_pk(user_id), "SK": K.prep_sk(app_id)})
        item = resp.get("Item")
        return _load(PrepPack, item) if item else None

    # --- account deletion ------------------------------------------------
    def delete_user_data(self, user_id: str) -> int:
        """Delete every item in the user's partition. Returns the count."""

        pk = K.user_pk(user_id)
        count = 0
        last_key: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": "PK = :pk",
                "ExpressionAttributeValues": {":pk": pk},
                "ProjectionExpression": "PK, SK",
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            resp = self._t.query(**kwargs)
            with self._t.batch_writer() as batch:
                for item in resp.get("Items", []):
                    batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
                    count += 1
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        return count

    # --- internal --------------------------------------------------------
    def _query_prefix(self, user_id: str, sk_prefix: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        last_key: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk)",
                "ExpressionAttributeValues": {
                    ":pk": K.user_pk(user_id),
                    ":sk": sk_prefix,
                },
            }
            if last_key:
                kwargs["ExclusiveStartKey"] = last_key
            resp = self._t.query(**kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        return items
