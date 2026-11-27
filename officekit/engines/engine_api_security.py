"""Browser-origin policy for the loopback-only OfficeKit desktop API."""

import hmac
import secrets
from collections.abc import Mapping
from urllib.parse import urlsplit


API_TOKEN_ENVIRONMENT_KEY = "OFFICEKIT_API_TOKEN"
MIN_API_TOKEN_LENGTH = 32
MAX_API_TOKEN_LENGTH = 128


TRUSTED_DESKTOP_ORIGINS = frozenset({
    "tauri://localhost",
    "http://tauri.localhost",
    "http://127.0.0.1:8000",
})

def _is_isolated_ui_test_origin(origin: str | None) -> bool:
    if not isinstance(origin, str):
        return False
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and port is not None
        and 1024 <= port <= 65535
        and origin == f"http://127.0.0.1:{port}"
    )


def trusted_api_origins(environment: Mapping[str, str] | None = None) -> frozenset[str]:
    """Return desktop origins, adding the local UI test origin only in an isolated test process."""
    values = environment or {}
    origins = set(TRUSTED_DESKTOP_ORIGINS)
    ui_test_origin = values.get("OFFICEKIT_UI_TEST_ORIGIN")
    if (
        _is_isolated_ui_test_origin(ui_test_origin)
        and values.get("OFFICEKIT_UI_TEST_TOKEN")
        and values.get(API_TOKEN_ENVIRONMENT_KEY)
    ):
        origins.add(ui_test_origin)
    return frozenset(origins)


def is_trusted_api_origin(origin: str | None, environment: Mapping[str, str] | None = None) -> bool:
    """Allow native clients without Origin and only configured desktop/test origins."""
    return origin is None or origin in trusted_api_origins(environment)


DEV_NOAUTH_ENVIRONMENT_KEY = "OFFICEKIT_DEV_NOAUTH"
DEV_UNLOCK_ENVIRONMENT_KEY = "OFFICEKIT_DEV_UNLOCK"
TRUSTED_API_HOSTS = ("127.0.0.1", "localhost", "testserver")


def resolve_api_auth_token(environment: Mapping[str, str]) -> str | None:
    """The bearer token the local API expects; `None` only when a developer opted out of auth.

    A missing token used to mean "no authentication". It now fails closed: without a token and
    without OFFICEKIT_DEV_NOAUTH=1, a random per-process token that nobody knows is used, so every
    /api/ request is refused instead of being open to any local process.
    """
    token = environment.get(API_TOKEN_ENVIRONMENT_KEY)
    if token is not None:
        return token
    if environment.get(DEV_NOAUTH_ENVIRONMENT_KEY) == "1":
        return None
    return secrets.token_urlsafe(32)


def dev_unlock_enabled(environment: Mapping[str, str]) -> bool:
    """Source-build switch: OFFICEKIT_DEV_UNLOCK=1 skips the licence gate for local development."""
    return environment.get(DEV_UNLOCK_ENVIRONMENT_KEY) == "1"


def load_sidecar_api_token(environment: Mapping[str, str]) -> str:
    """Require an unpredictable process token before launching the packaged sidecar."""
    token = environment.get(API_TOKEN_ENVIRONMENT_KEY)
    if (
        not isinstance(token, str)
        or not MIN_API_TOKEN_LENGTH <= len(token) <= MAX_API_TOKEN_LENGTH
        or not token.isascii()
        or any(not character.isprintable() or character.isspace() for character in token)
    ):
        raise RuntimeError("The OfficeKit sidecar requires a valid desktop API token")
    return token


def is_api_authorization_valid(authorization: str | None, expected_token: str | None) -> bool:
    """Constant-time bearer-token check; a missing expected token denotes dev mode only."""
    if expected_token is None:
        return True
    if (
        not isinstance(authorization, str)
        or not expected_token
        or len(authorization) > MAX_API_TOKEN_LENGTH + 16
    ):
        return False
    parts = authorization.split()
    return (
        len(parts) == 2
        and parts[0].casefold() == "bearer"
        and parts[1].isascii()
        and hmac.compare_digest(parts[1], expected_token)
    )
