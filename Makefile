# Common development tasks. Backend commands run inside backend/ with uv.
.PHONY: help install lint format typecheck test test-unit test-integration migrate

BACKEND := cd backend &&

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

install: ## Install backend dependencies
	$(BACKEND) uv sync

lint: ## Ruff lint (incl. provider/Neo4j import rules)
	$(BACKEND) uv run ruff check . && uv run ruff format --check .

format: ## Auto-format
	$(BACKEND) uv run ruff format . && uv run ruff check --fix .

typecheck: ## mypy --strict
	$(BACKEND) uv run mypy

test-unit: ## Unit tests (no database)
	$(BACKEND) uv run pytest tests/unit

test-integration: ## Integration tests (needs TEST_DATABASE_ADMIN_URL)
	$(BACKEND) uv run pytest tests/integration

test: ## All backend tests
	$(BACKEND) uv run pytest

migrate: ## Apply migrations to DATABASE_URL
	$(BACKEND) uv run alembic upgrade head
