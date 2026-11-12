"""R0-9: every project-scoped route resolves a project scope (route inventory)."""

from __future__ import annotations

from fastapi.dependencies.models import Dependant

from researchpilot.api.app import iter_api_routes
from researchpilot.api.deps import SCOPE_RESOLVERS

# Routes that are deliberately not project-scoped: health, and user-level collections that
# filter by the caller's memberships themselves.
NOT_PROJECT_SCOPED = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ready"),
    ("GET", "/api/v1/health/dependencies"),
    ("POST", "/api/v1/projects"),
    ("GET", "/api/v1/projects"),
    ("GET", "/api/v1/dashboard"),
    # The caller's own preferences (display time zone); they touch only the user's own row.
    ("GET", "/api/v1/me/preferences"),
    ("PUT", "/api/v1/me/preferences"),
}


def _calls(dependant: Dependant) -> set[object]:
    found = {dependant.call}
    for sub in dependant.dependencies:
        found |= _calls(sub)
    return found


def test_every_other_route_depends_on_a_scope_resolver() -> None:
    missing = []
    for path, route in iter_api_routes():
        for method in route.methods:
            if (method, path) in NOT_PROJECT_SCOPED:
                continue
            if not _calls(route.dependant) & set(SCOPE_RESOLVERS):
                missing.append(f"{method} {path}")
    assert missing == [], f"routes without project scope: {missing}"


def test_allowlist_has_no_stale_entries() -> None:
    existing = {(m, p) for p, r in iter_api_routes() for m in r.methods}
    assert existing >= NOT_PROJECT_SCOPED


def test_routes_with_scoped_ids_are_never_allowlisted() -> None:
    for _method, path in NOT_PROJECT_SCOPED:
        assert not any(k in path for k in ("{project_id}", "{run_id}", "{checkpoint_id}")), path
