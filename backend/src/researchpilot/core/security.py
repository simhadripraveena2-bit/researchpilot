"""Startup security checks (ARCHITECTURE §11, R0-9)."""

from __future__ import annotations

import ipaddress

from researchpilot.core.errors import InsecureConfiguration
from researchpilot.core.settings import AuthMode, Settings

_LOCAL_NAMES = {"localhost"}


def is_loopback(host: str) -> bool:
    if host in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def assert_safe_startup(settings: Settings) -> None:
    """Refuse configurations that would expose an unauthenticated server.

    * ``AUTH_MODE=disabled`` is allowed only on a loopback bind, or inside the local Compose
      stack (``CONTAINER_LOCAL=true``) whose published ports are bound to 127.0.0.1.
    * Hosted authentication modes are gate-H work and are not implemented yet, so they are
      refused rather than silently running without auth.
    """
    if settings.auth_mode is not AuthMode.DISABLED:
        raise InsecureConfiguration(
            f"AUTH_MODE={settings.auth_mode.value} is not implemented yet (gate H); "
            "hosted deployment is blocked"
        )
    if not is_loopback(settings.bind_host) and not settings.container_local:
        raise InsecureConfiguration(
            f"refusing to bind to {settings.bind_host!r} with authentication disabled; "
            "use 127.0.0.1 (local use) or enable authentication (gate H)"
        )
