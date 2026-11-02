"""Models for the shared classifier API: invite codes and usage.

Stored in a dedicated DynamoDB table (``JobTrackerCodes``) that is isolated from
the application table. Codes are identified by a public ``code_id`` and verified
against a stored hash of the secret code (the raw code is never stored).
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InviteCode(_Model):
    """A per-friend invite code with daily request/token caps."""

    code_id: str  # public id (shown in admin listings), e.g. "jt_ab12cd"
    code_hash: str  # sha256 of the full secret code; raw code never stored
    label: str  # friend name / note, e.g. "Sam"
    created_at: dt.datetime
    revoked_at: dt.datetime | None = None
    # caps (per UTC day)
    daily_request_cap: int = 300
    daily_token_cap: int = 2_000_000

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class DailyUsage(_Model):
    """Per-code, per-UTC-day usage counters."""

    code_id: str
    day: str  # YYYY-MM-DD (UTC)
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    throttled: int = 0  # requests rejected for hitting a cap
    last_used_at: dt.datetime | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class UsageReportRow(_Model):
    """A row in the admin usage report."""

    code_id: str
    label: str
    active: bool
    requests_today: int
    tokens_today: int
    requests_total: int
    tokens_total: int
    est_cost_total_usd: float = Field(default=0.0)
    last_used_at: dt.datetime | None = None
