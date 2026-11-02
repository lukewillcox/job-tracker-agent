"""Microsoft identity platform configuration.

Non-secret values are safe to keep here / in env. The client *secret* is never
stored in code: it lives in Secrets Manager and is read at runtime.

The dev Entra app registration ("Job Tracker (dev)"):
  - client id:    8f599315-1e39-4015-9924-fb0bf1e92974
  - sign-in authority: "common" (any Entra tenant + personal Microsoft accounts)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Delegated scopes requested at sign-in (Requirement 1.2). offline_access gives
# the refresh token; openid/profile/email are reserved OIDC scopes that MSAL
# adds itself, so they are not listed here.
GRAPH_SCOPES: tuple[str, ...] = (
    "User.Read",
    "Mail.Read",
    "Calendars.ReadWrite",
    "Files.ReadWrite",
)

# "common" lets both work/school and personal Microsoft accounts sign in.
AUTHORITY = "https://login.microsoftonline.com/common"

# Default dev client id (overridable by env for prod).
_DEFAULT_CLIENT_ID = "8f599315-1e39-4015-9924-fb0bf1e92974"


@dataclass(frozen=True)
class MsConfig:
    client_id: str
    authority: str
    # Only needed for the auth-code flow (login/callback). Token refresh — which
    # the scan pipeline uses — does not need it, so it is optional.
    redirect_uri: str | None
    scopes: tuple[str, ...]

    def require_redirect_uri(self) -> str:
        if not self.redirect_uri:
            raise RuntimeError("MS_REDIRECT_URI is not set (required for sign-in)")
        return self.redirect_uri


def load_config() -> MsConfig:
    """Build the MS config from the environment."""

    return MsConfig(
        client_id=os.environ.get("MS_CLIENT_ID", _DEFAULT_CLIENT_ID),
        authority=os.environ.get("MS_AUTHORITY", AUTHORITY),
        redirect_uri=os.environ.get("MS_REDIRECT_URI"),
        scopes=GRAPH_SCOPES,
    )
