# syntax=docker/dockerfile:1.7
# One image for the API, the worker and the one-shot migration job.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Optional extra CA certificate (e.g. a corporate TLS-inspecting proxy), passed as a build
# secret so it never ends up in an image layer. Absent/empty in normal builds.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir uv==0.11.32

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY config ./config
COPY prompts ./prompts
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev

RUN useradd --system --uid 10001 --home /app researchpilot && \
    mkdir -p /app/var/storage && chown -R researchpilot /app/var
USER researchpilot
ENV PATH=/app/.venv/bin:$PATH

EXPOSE 8000
CMD ["python", "-m", "researchpilot.api"]
