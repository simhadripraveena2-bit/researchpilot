"""RFC 7807 problem+json responses for every error (ARCHITECTURE §2.3)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from researchpilot.core.errors import ResearchPilotError

PROBLEM = "application/problem+json"
_TYPE_BASE = "https://researchpilot.dev/problems/"


def problem(
    status: int, code: str, title: str, detail: str | None = None, **extra: Any
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": _TYPE_BASE + code.replace("_", "-"),
        "title": title,
        "status": status,
        "code": code,
    }
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ResearchPilotError)
    async def _domain(_: Request, exc: ResearchPilotError) -> JSONResponse:
        code = exc.code
        if code == "capability_unavailable":
            code = "graph_capability_unavailable"
        return problem(exc.status, code, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return problem(422, "validation_failed", "Validation failed", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem(exc.status_code, "http_error", str(exc.detail))
