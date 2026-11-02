"""Client for the host's shared classifier API.

Sends batches of stripped emails to ``POST /classify`` with the invite code as a
Bearer token, and parses the returned facts into :class:`EmailFacts`. The body
text sent is already signature/quote-stripped and truncated by the ingest step.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from domain.models import EmailFacts

# Batch size is bounded by the API Gateway HTTP API 30s integration timeout:
# each email is ~1-1.5s of Bedrock, so 8/batch (~12s) stays comfortably under it.
_BATCH = 8
_TIMEOUT = 35


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
            try:
                results, u = self._post(batch)
            except ClassifyApiError as exc:
                # auth/cap errors are fatal and should surface; transient batch
                # failures (503 after retries) just leave this batch for next scan
                if exc.status in (401, 403, 429):
                    raise
                for _ in batch:
                    out.append(ClassifiedEmail(facts=None, capped=False))
                continue
            out.extend(results)
            usage.classified += u.classified
            usage.capped += u.capped
            usage.tokens_in += u.tokens_in
            usage.tokens_out += u.tokens_out
        return out, usage

    def _post(self, batch: list[dict]) -> tuple[list[ClassifiedEmail], ClassifyUsage]:
        # retry transient gateway/timeout errors (503, 504, 429, network) with
        # backoff; a hard auth/limit error (401/403/429-cap) is raised to the CLI.
        import time

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(
                    self._url,
                    headers={
                        "Authorization": f"Bearer {self._code}",
                        "Content-Type": "application/json",
                    },
                    json={"timezone": self._tz, "emails": batch},
                    timeout=_TIMEOUT,
                )
            except requests.RequestException as exc:
                last_exc = exc
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code in (502, 503, 504):
                last_exc = ClassifyApiError(resp.status_code, _safe_error(resp))
                time.sleep(2 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise ClassifyApiError(resp.status_code, _safe_error(resp))
            return self._parse(resp.json())
        # exhausted retries: treat this batch as unclassified (try next scan),
        # don't abort the whole run
        raise ClassifyApiError(503, f"batch failed after retries: {last_exc}")

    def _parse(self, body: dict) -> tuple[list[ClassifiedEmail], ClassifyUsage]:
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
