"""Client for the host's shared classifier API.

Sends batches of stripped emails to ``POST /classify`` with the invite code as a
Bearer token, and parses the returned facts into :class:`EmailFacts`. The body
text sent is already signature/quote-stripped and truncated by the ingest step.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from domain.models import EmailFacts

_BATCH = 25
_TIMEOUT = 90


@dataclass
class ClassifiedEmail:
    facts: EmailFacts | None  # None when the daily cap was hit for this one
    capped: bool


@dataclass
class ClassifyUsage:
    classified: int = 0
    capped: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


class ClassifyApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class ClassifyClient:
    def __init__(self, api_url: str, invite_code: str, timezone: str = "Europe/London") -> None:
        self._url = api_url.rstrip("/") + "/classify"
        self._code = invite_code
        self._tz = timezone

    def classify(self, emails: list[dict]) -> tuple[list[ClassifiedEmail], ClassifyUsage]:
        out: list[ClassifiedEmail] = []
        usage = ClassifyUsage()
        for i in range(0, len(emails), _BATCH):
            batch = emails[i : i + _BATCH]
            results, u = self._post(batch)
            out.extend(results)
            usage.classified += u.classified
            usage.capped += u.capped
            usage.tokens_in += u.tokens_in
            usage.tokens_out += u.tokens_out
        return out, usage

    def _post(self, batch: list[dict]) -> tuple[list[ClassifiedEmail], ClassifyUsage]:
        resp = requests.post(
            self._url,
            headers={
                "Authorization": f"Bearer {self._code}",
                "Content-Type": "application/json",
            },
            json={"timezone": self._tz, "emails": batch},
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            msg = _safe_error(resp)
            raise ClassifyApiError(resp.status_code, msg)
        body = resp.json()
        results = [
            ClassifiedEmail(
                facts=EmailFacts.model_validate(r["facts"]) if "facts" in r else None,
                capped=bool(r.get("capped")),
            )
            for r in body.get("results", [])
        ]
        u = body.get("usage", {})
        return results, ClassifyUsage(
            classified=int(u.get("classified", 0)),
            capped=int(u.get("capped", 0)),
            tokens_in=int(u.get("tokens_in", 0)),
            tokens_out=int(u.get("tokens_out", 0)),
        )


def _safe_error(resp: requests.Response) -> str:
    try:
        return str(resp.json().get("error", resp.reason))
    except Exception:
        return resp.reason or "request failed"
