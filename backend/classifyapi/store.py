"""DynamoDB access for the shared classifier API (isolated codes table).

Single table ``JobTrackerCodes`` with two item kinds:

    InviteCode    PK=CODE#{code_id}            SK=META
    DailyUsage    PK=CODE#{code_id}            SK=USAGE#{YYYY-MM-DD}

Cap enforcement is atomic: :meth:`charge_request` does a single conditional
``update_item`` that increments the day's counters only if the new totals stay
within the code's caps, so concurrent requests cannot overshoot. The request is
"reserved" before the Bedrock call; actual token usage is reconciled after.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

from classifyapi.models import DailyUsage, InviteCode

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

_USAGE_TTL_DAYS = 45  # keep ~6 weeks of daily rows for the usage report


def _code_pk(code_id: str) -> str:
    return f"CODE#{code_id}"


def _usage_sk(day: str) -> str:
    return f"USAGE#{day}"


def _search_sk(month: str) -> str:
    return f"SEARCH#{month}"


def _today() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")


def _this_month() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m")


class CapExceededError(RuntimeError):
    """Raised when a request would exceed the code's daily request/token cap."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SearchCapError(RuntimeError):
    """Raised when the monthly search-query cap is reached."""

    def __init__(self, used: int, cap: int) -> None:
        super().__init__(f"monthly search cap reached ({used}/{cap})")
        self.used = used
        self.cap = cap


class CodeStore:
    def __init__(self, table: Table) -> None:
        self._t = table

    # --- admin: codes ----------------------------------------------------
    def put_code(self, code: InviteCode) -> None:
        self._t.put_item(
            Item={
                "PK": _code_pk(code.code_id),
                "SK": "META",
                "data": json.loads(code.model_dump_json()),
            }
        )

    def get_code(self, code_id: str) -> InviteCode | None:
        resp = self._t.get_item(Key={"PK": _code_pk(code_id), "SK": "META"})
        item = resp.get("Item")
        return InviteCode.model_validate(item["data"]) if item else None

    def revoke_code(self, code_id: str, when: dt.datetime | None = None) -> bool:
        code = self.get_code(code_id)
        if code is None or code.revoked_at is not None:
            return False
        code = code.model_copy(update={"revoked_at": when or dt.datetime.now(dt.UTC)})
        self.put_code(code)
        return True

    def list_codes(self) -> list[InviteCode]:
        codes: list[InviteCode] = []
        last: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "FilterExpression": "SK = :m",
                "ExpressionAttributeValues": {":m": "META"},
            }
            if last:
                kwargs["ExclusiveStartKey"] = last
            resp = self._t.scan(**kwargs)
            codes.extend(InviteCode.model_validate(i["data"]) for i in resp.get("Items", []))
            last = resp.get("LastEvaluatedKey")  # type: ignore[assignment]
            if not last:
                break
        return codes

    # --- usage -----------------------------------------------------------
    def get_usage(self, code_id: str, day: str | None = None) -> DailyUsage:
        day = day or _today()
        resp = self._t.get_item(Key={"PK": _code_pk(code_id), "SK": _usage_sk(day)})
        item = resp.get("Item")
        if not item:
            return DailyUsage(code_id=code_id, day=day)
        return DailyUsage.model_validate(
            {
                "code_id": code_id,
                "day": day,
                "requests": int(item.get("requests", 0)),
                "input_tokens": int(item.get("input_tokens", 0)),
                "output_tokens": int(item.get("output_tokens", 0)),
                "throttled": int(item.get("throttled", 0)),
                "alerted_50": bool(item.get("alerted_50", False)),
                "last_used_at": item.get("last_used_at"),
            }
        )

    def list_usage(self, code_id: str) -> list[DailyUsage]:
        resp = self._t.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :u)",
            ExpressionAttributeValues={":pk": _code_pk(code_id), ":u": "USAGE#"},
        )
        out: list[DailyUsage] = []
        for item in resp.get("Items", []):
            day = str(item["SK"]).split("#", 1)[1]
            out.append(
                DailyUsage(
                    code_id=code_id,
                    day=day,
                    requests=int(item.get("requests", 0)),
                    input_tokens=int(item.get("input_tokens", 0)),
                    output_tokens=int(item.get("output_tokens", 0)),
                    throttled=int(item.get("throttled", 0)),
                )
            )
        return out

    def charge_request(self, code: InviteCode) -> None:
        """Atomically reserve one request against the day's caps.

        Increments ``requests`` by 1 only if it would not exceed the request
        cap and the token cap has not already been passed. Raises
        :class:`CapExceededError` if a cap is hit (also bumping ``throttled``).
        """

        day = _today()
        ttl = int(
            (dt.datetime.now(dt.UTC) + dt.timedelta(days=_USAGE_TTL_DAYS)).timestamp()
        )
        now_iso = dt.datetime.now(dt.UTC).isoformat()
        try:
            # DynamoDB condition expressions cannot do arithmetic, so compare a
            # maintained `total_tokens` attribute directly against the token cap.
            self._t.update_item(
                Key={"PK": _code_pk(code.code_id), "SK": _usage_sk(day)},
                UpdateExpression=(
                    "SET last_used_at = :now, #ttl = :ttl ADD requests :one"
                ),
                ConditionExpression=(
                    "(attribute_not_exists(requests) OR requests < :rcap) "
                    "AND (attribute_not_exists(total_tokens) OR total_tokens < :tcap)"
                ),
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":one": 1,
                    ":now": now_iso,
                    ":ttl": ttl,
                    ":rcap": code.daily_request_cap,
                    ":tcap": code.daily_token_cap,
                },
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                self._bump_throttled(code.code_id, day, ttl)
                raise CapExceededError("daily cap reached") from exc
            raise

    def record_tokens(self, code_id: str, input_tokens: int, output_tokens: int) -> None:
        """Reconcile actual token usage after a successful Bedrock call."""

        day = _today()
        self._t.update_item(
            Key={"PK": _code_pk(code_id), "SK": _usage_sk(day)},
            UpdateExpression=(
                "ADD input_tokens :i, output_tokens :o, total_tokens :t"
            ),
            ExpressionAttributeValues={
                ":i": int(input_tokens),
                ":o": int(output_tokens),
                ":t": int(input_tokens) + int(output_tokens),
            },
        )

    # --- monthly search cap (Prospects) ----------------------------------
    def charge_searches(self, code_id: str, n: int, monthly_cap: int) -> tuple[int, int]:
        """Atomically reserve ``n`` searches against the month's cap.

        Returns (used_after, remaining). Raises :class:`SearchCapError` if the
        reservation would exceed the cap. A single conditional ADD, so
        concurrent runs can't overshoot the free Brave credit.
        """

        month = _this_month()
        ttl = int((dt.datetime.now(dt.UTC) + dt.timedelta(days=65)).timestamp())
        try:
            resp = self._t.update_item(
                Key={"PK": _code_pk(code_id), "SK": _search_sk(month)},
                UpdateExpression="SET #ttl = :ttl ADD searches :n",
                ConditionExpression=(
                    "attribute_not_exists(searches) OR searches <= :room"
                ),
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":n": n,
                    ":ttl": ttl,
                    ":room": monthly_cap - n,
                },
                ReturnValues="UPDATED_NEW",
            )
            used = int(resp["Attributes"]["searches"])
            return used, monthly_cap - used
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise SearchCapError(self.searches_used(code_id), monthly_cap) from exc
            raise

    def searches_used(self, code_id: str, month: str | None = None) -> int:
        resp = self._t.get_item(
            Key={"PK": _code_pk(code_id), "SK": _search_sk(month or _this_month())}
        )
        item = resp.get("Item")
        return int(item.get("searches", 0)) if item else 0

    def try_claim_50pct_alert(self, code_id: str) -> bool:
        """Set the per-day 'alerted at 50%' flag, returning True only once.

        A conditional write so exactly one concurrent Lambda sends the alert.
        """

        day = _today()
        try:
            self._t.update_item(
                Key={"PK": _code_pk(code_id), "SK": _usage_sk(day)},
                UpdateExpression="SET alerted_50 = :t",
                ConditionExpression="attribute_not_exists(alerted_50) OR alerted_50 = :f",
                ExpressionAttributeValues={":t": True, ":f": False},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def _bump_throttled(self, code_id: str, day: str, ttl: int) -> None:
        self._t.update_item(
            Key={"PK": _code_pk(code_id), "SK": _usage_sk(day)},
            UpdateExpression="ADD throttled :one SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":one": 1, ":ttl": ttl},
        )
