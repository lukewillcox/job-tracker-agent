"""Local on-disk store for the user's applications and events.

A single JSON file under ``~/.jobtracker/data.json``. Holds the same Pydantic
:class:`Application` models the backend uses, so the shared matcher/state machine
and Excel builder work unchanged. No email content is stored (only extracted
facts, per the product principle).
"""

from __future__ import annotations

import json
from pathlib import Path

from domain.models import Application

from jobtracker_cli.config import CONFIG_DIR

DATA_PATH = CONFIG_DIR / "data.json"


class LocalStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DATA_PATH
        self._apps: dict[str, Application] = {}
        self._processed: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        raw = json.loads(self._path.read_text())
        self._apps = {
            a["app_id"]: Application.model_validate(a) for a in raw.get("applications", [])
        }
        self._processed = set(raw.get("processed", []))

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "applications": [json.loads(a.model_dump_json()) for a in self._apps.values()],
            "processed": sorted(self._processed),
        }
        self._path.write_text(json.dumps(payload, indent=2))
        self._path.chmod(0o600)

    def applications(self) -> list[Application]:
        return [a for a in self._apps.values() if a.deleted_at is None]

    def all_applications(self) -> list[Application]:
        return list(self._apps.values())

    def put_application(self, app: Application) -> None:
        self._apps[app.app_id] = app

    def is_processed(self, internet_message_id: str) -> bool:
        return internet_message_id in self._processed

    def mark_processed(self, internet_message_id: str) -> None:
        self._processed.add(internet_message_id)
