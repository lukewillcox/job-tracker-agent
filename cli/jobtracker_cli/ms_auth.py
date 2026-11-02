"""Microsoft sign-in for the CLI, via the device-code flow.

A locally-installed CLI is a *public* client (no client secret), so it uses the
device-code flow: we print a URL and a code, the user signs in in their browser,
and MSAL polls until done. The resulting refresh token is stored in the Keychain
and exchanged for access tokens on each scan.

The same Entra app registration is reused, but it must have "Allow public client
flows" enabled for device-code to work (documented in setup).
"""

from __future__ import annotations

from collections.abc import Callable

import msal

# Same delegated scopes as the hosted app (read-only mail + the write scopes the
# product uses). openid/profile/offline_access are added by MSAL.
SCOPES = ["User.Read", "Mail.Read", "Calendars.ReadWrite", "Files.ReadWrite"]
AUTHORITY = "https://login.microsoftonline.com/common"

# The CLI uses the same public client id as the app registration.
DEFAULT_CLIENT_ID = "8f599315-1e39-4015-9924-fb0bf1e92974"


class SignInError(RuntimeError):
    pass


def device_code_sign_in(
    client_id: str = DEFAULT_CLIENT_ID,
    prompt: Callable[[str], None] = print,
) -> str:
    """Run the device-code flow; return the refresh token.

    ``prompt`` is called with the human instruction (URL + code).
    """

    app = msal.PublicClientApplication(client_id, authority=AUTHORITY)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise SignInError(flow.get("error_description", "could not start device flow"))
    prompt(flow["message"])  # e.g. "To sign in, visit ... and enter code ABCD-EFGH"
    result = app.acquire_token_by_device_flow(flow)  # blocks until the user finishes
    if "refresh_token" not in result:
        raise SignInError(result.get("error_description", "sign-in failed"))
    return str(result["refresh_token"])


def access_token_from_refresh(
    refresh_token: str, client_id: str = DEFAULT_CLIENT_ID
) -> tuple[str, str | None]:
    """Exchange a refresh token for (access_token, rotated_refresh_token)."""

    app = msal.PublicClientApplication(client_id, authority=AUTHORITY)
    result = app.acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
    if "access_token" not in result:
        raise SignInError(result.get("error_description", "token refresh failed"))
    return str(result["access_token"]), result.get("refresh_token")
