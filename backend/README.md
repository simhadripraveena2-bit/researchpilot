# ResearchPilot backend

FastAPI API, worker and domain services. See `docs/ARCHITECTURE.md` at the repository root.

```bash
uv sync                      # install
uv run alembic upgrade head  # migrate (needs DATABASE_URL)
uv run pytest                # tests (integration tests need TEST_DATABASE_ADMIN_URL)
uv run ruff check . && uv run mypy
```
