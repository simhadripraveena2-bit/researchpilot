"""Domain errors. The API maps them to RFC 7807 problem+json responses."""

from __future__ import annotations

from typing import Any


class ResearchPilotError(Exception):
    """Base error with a stable machine-readable code and HTTP status."""

    code: str = "internal_error"
    status: int = 500
    title: str = "Internal error"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra


class NotFound(ResearchPilotError):
    code, status, title = "not_found", 404, "Not found"


class ValidationFailed(ResearchPilotError):
    code, status, title = "validation_failed", 422, "Validation failed"


class ScopeRequired(ResearchPilotError):
    code, status, title = "project_scope_required", 400, "Project scope required"


class Forbidden(ResearchPilotError):
    code, status, title = "forbidden", 403, "Forbidden"


class DependencyUnavailable(ResearchPilotError):
    code, status, title = "dependency_unavailable", 503, "Dependency unavailable"


class CapabilityUnavailable(ResearchPilotError):
    code, status, title = "capability_unavailable", 501, "Capability unavailable"


class GraphCapabilityUnavailable(CapabilityUnavailable):
    code = "graph_capability_unavailable"


class InsecureConfiguration(ResearchPilotError):
    code, status, title = "insecure_configuration", 500, "Insecure configuration"


class Conflict(ResearchPilotError):
    code, status, title = "conflict", 409, "Conflict"
