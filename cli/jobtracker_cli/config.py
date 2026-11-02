"""Local config + secret storage.

Non-secret config lives in ``~/.jobtracker/config.json``. Secrets (the invite
code and the Microsoft refresh token) go in the macOS Keychain via ``keyring``,
never on disk in plaintext.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import keyring

CONFIG_DIR = Path.home() / ".jobtracker"
CONFIG_PATH = CONFIG_DIR / "config.json"
_KEYRING_SERVICE = "jobtracker"
_INVITE_KEY = "invite_code"
_REFRESH_KEY = "ms_refresh_token"


@dataclass
class Config:
    username: str = ""
    email: str = ""
    api_url: str = ""
    timezone: str = "Europe/London"
    backfill_months: int = 3
    schedule: str = "every_2_days"  # every_2_days | daily | weekly | off
    delta_links: dict[str, str] = field(default_factory=dict)
    last_scan_at: str | None = None
    scan_count: int = 0
    # cumulative token usage, for the local "beer tab" in `status`
    tokens_in_total: int = 0
    tokens_out_total: int = 0

    @classmethod
    def load(cls) -> Config:
        if not CONFIG_PATH.exists():
            return cls()
        data = json.loads(CONFIG_PATH.read_text())
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2))
        CONFIG_PATH.chmod(0o600)


# --- secrets (macOS Keychain) -------------------------------------------
def set_invite_code(code: str) -> None:
    keyring.set_password(_KEYRING_SERVICE, _INVITE_KEY, code)


def get_invite_code() -> str | None:
    return keyring.get_password(_KEYRING_SERVICE, _INVITE_KEY)


def set_refresh_token(token: str) -> None:
    keyring.set_password(_KEYRING_SERVICE, _REFRESH_KEY, token)


def get_refresh_token() -> str | None:
    return keyring.get_password(_KEYRING_SERVICE, _REFRESH_KEY)


def clear_secrets() -> None:
    import contextlib

    for key in (_INVITE_KEY, _REFRESH_KEY):
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(_KEYRING_SERVICE, key)
