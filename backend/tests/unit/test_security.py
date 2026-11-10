"""R0-9: the server refuses a non-local bind with authentication disabled."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from researchpilot.core.errors import InsecureConfiguration
from researchpilot.core.security import assert_safe_startup, is_loopback
from researchpilot.core.settings import AuthMode, Settings

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "127.0.0.2"])
def test_loopback_binds_are_allowed(host: str) -> None:
    assert is_loopback(host)
    assert_safe_startup(Settings(bind_host=host, _env_file=None))


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "example.com"])
def test_non_local_bind_without_auth_is_refused(host: str) -> None:
    with pytest.raises(InsecureConfiguration, match="authentication disabled"):
        assert_safe_startup(Settings(bind_host=host, _env_file=None))


def test_hosted_auth_modes_are_refused_until_gate_h() -> None:
    for mode in (AuthMode.OIDC, AuthMode.PASSWORD):
        with pytest.raises(InsecureConfiguration, match="gate H"):
            assert_safe_startup(Settings(auth_mode=mode, _env_file=None))


def test_container_mode_allows_wildcard_bind_inside_the_container() -> None:
    assert_safe_startup(Settings(bind_host="0.0.0.0", container_local=True, _env_file=None))


def test_compose_publishes_ports_on_localhost_only() -> None:
    """CONTAINER_LOCAL is only safe because Compose never publishes on a public interface."""
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port} publicly"
        env = service.get("environment", {})
        if str(env.get("CONTAINER_LOCAL", "false")).lower() == "true":
            assert env.get("AUTH_MODE", "disabled") == "disabled"
