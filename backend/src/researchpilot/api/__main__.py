"""``python -m researchpilot.api`` - serve the API after the startup security check."""

from __future__ import annotations

import uvicorn

from researchpilot.core.security import assert_safe_startup
from researchpilot.core.settings import get_settings


def main() -> None:
    settings = get_settings()
    assert_safe_startup(settings)  # refuses a non-local bind without authentication (R0-9)
    uvicorn.run(
        "researchpilot.api.app:create_app",
        factory=True,
        host=settings.bind_host,
        port=settings.bind_port,
        proxy_headers=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
