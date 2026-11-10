# R0 implementation notes

Status of the R0 foundation as built, for review before R1. The canonical design is in the
other documents in `docs/`; this file records how R0 implements it and where it deviates.

## What was built

**PR 1: scaffold, database and LLM gateway skeleton**
- `backend/` (uv, Python 3.12+, ruff, mypy --strict, pytest), Makefile, `.env.example`,
  pre-commit (ruff, gitleaks), backend CI workflow.
- Core: environment settings (secrets as `SecretStr`), UUIDv7 IDs, injectable clock, domain
  errors, structured JSON logging with secret redaction.
- Database: migration `0001` with users, projects, project members, research items,
  `graph_nodes`, `node_source_registry`, runs, task executions, run events, checkpoints,
  outbox (`domain_events` + per-consumer `domain_event_deliveries`) and claims.
- Graph readiness in SQL: `row_version` trigger; node registration trigger driven by
  `node_source_registry` (label, scope rule, condition); immutable node kind/scope;
  `rp_attach_node_source()` as the only way to make a table a node source.
- LLM gateway: provider-neutral interface, task → provider/model configuration (marked
  provisional until D1), versioned prompts, schema + semantic validation with exactly one
  repair attempt, refusal/truncation errors, fake provider, Anthropic adapter.

**PR 2: API, worker, SSE, frontend shell, Compose and security scaffolding**
- Migration `0002`: `jobs` table, single-local-user index, and a `langgraph` schema.
- Postgres job queue (SKIP LOCKED claiming, heartbeats, retries with backoff, stale-lock
  reclaim); worker process; idempotent outbox dispatcher.
- LangGraph runner on the Postgres checkpointer; dummy workflow (LLM gateway call → human
  checkpoint → finish); run lifecycle service; SSE progress stream (NOTIFY + Last-Event-ID).
- FastAPI app: health/readiness/dependencies, projects (create, list, read, update,
  archive), dashboard, journey, runs, checkpoints, graph views; RFC 7807 errors.
- Security scaffolding: project-scope resolvers on every project-scoped route (route
  inventory test), 404 for projects the user is not a member of, startup refusal of a
  non-local bind without authentication, refusal of not-yet-implemented auth modes, private
  content-addressed file storage.
- `GraphService` interface with the PostgreSQL implementation skeleton and backend-neutral
  `GraphView`; multi-hop paths return `graph-capability-unavailable` (available from R2).
- Journey registry with the nine stages and one next step.
- Frontend shell (Vite, React 18, TypeScript, Tailwind, TanStack Query, React Router):
  dashboard, three-field new-project form, project overview with journey bar, system-check
  run view with live progress and a confirm/stop checkpoint.
- Docker images (backend, frontend/nginx), Compose stack (postgres+pgvector, migrate, api,
  worker, frontend, grobid; all ports on 127.0.0.1), frontend and stack CI workflows.

## R0 acceptance tests

| Test | Where | Status |
|---|---|---|
| R0-1 `make up` from a clean clone, all services healthy | `make up`, `.github/workflows/stack.yml` | pass locally (all 6 services healthy; end-to-end smoke test and UI flow through nginx); CI workflow not yet run on GitHub |
| R0-2 readiness 200 / problem+json 503 | `tests/integration/test_api.py` | pass |
| R0-3 SSE streaming, checkpoint pause, worker restart, resume | `tests/integration/test_runs_e2e.py` | pass (incl. crash mid-step) |
| R0-4 rolled-back events never dispatched; idempotent retries | `tests/integration/test_outbox.py` | pass |
| R0-5 secrets never logged | `tests/unit/test_logging.py` | pass |
| R0-6 migrations up/down/up; models match migrations | `tests/integration/test_migrations.py` | pass |
| R0-7 nine stages, deterministic states, one next step | `tests/unit/test_journey.py`, `test_api.py` | pass |
| R0-8 provider independence (fake swap, lint rule, manifest) | `test_llm_config.py`, `test_import_rules.py`, `test_runs_e2e.py` | pass |
| R0-9 project scope on every route; no non-local bind without auth | `test_route_inventory.py`, `test_security.py`, `test_api.py` | pass |
| R0-10 graph readiness (registration, conditions, immutability, GraphService, lint) | `test_graph_readiness.py`, `test_api.py`, `test_import_rules.py` | pass |

## Decisions and deviations

| # | Topic | What was done | Why |
|---|---|---|---|
| 1 | Delivery | Two commits ("R0 PR1", "R0 PR2") on the designated branch, not two GitHub pull requests | The repository has only this branch, so there is no base branch to open PRs against |
| 2 | Enums | VARCHAR + CHECK constraints instead of native Postgres enum types | Allowed by the schema doc; makes adding values and downgrades simple |
| 3 | `scope_rule = self` | Added for `projects` (a project node is scoped to itself) | Not in the documented set (global, own_project_id, parent_project) |
| 4 | `parent_project` | Recognised but refused by the trigger until R1 | It depends on `structural_relations`, which arrives in R1 |
| 5 | Extra tables/columns | `domain_event_deliveries`, `jobs`, `research_runs.heartbeat_at`, `uq_users_single_local` | Per-consumer idempotent outbox delivery; job queue; zombie-run detection; one implicit local user |
| 6 | Job queue | A small in-house Postgres queue instead of a library such as procrastinate | D3 asks for a Postgres-backed queue; this needs no extra schema/library and is fully tested |
| 7 | LangGraph tables | Created by LangGraph's own `setup()` in a separate `langgraph` schema | Keeps them outside Alembic-managed `public`; downgrade drops the schema |
| 8 | Claim evidence | `evidence_span_id` and `signal_id` have no foreign keys yet | Their target tables arrive in R1 |
| 9 | Project owner column | `projects.user_id` (the owner) plus `project_members` | Matches the schema doc |
| 10 | Compose binding | `CONTAINER_LOCAL=true` lets the API bind 0.0.0.0 inside its container; a test requires every published port to be on 127.0.0.1 | The container must listen on its network interface; exposure is controlled by the published ports |
| 11 | LLM in the local stack | `LLM_FORCE_FAKE=true` by default in Compose; manifests record the provider actually used | D1 is open and no key is configured; the system check still exercises the gateway |
| 12 | Anthropic adapter | Implemented (structured output, effort, server-side refusal fallbacks, error mapping) but not run against the live API; no streaming yet | No API key in this environment; streaming is needed from M1d |
| 13 | Graph endpoint paths | `/projects/{id}/graph/nodes/{uid}/neighbors` and `/projects/{id}/graph/paths` instead of `/graph/...` | Makes the project scope explicit in the route (every graph call requires a scope) |
| 14 | Frontend API types | Hand-written for R0 | Generation from the OpenAPI document is planned with R1's larger API |
| 15 | GROBID image | `lfoppiano/grobid:0.8.1` (CPU, CRF models) | Smaller image; the deep-learning image can be swapped in later |
| 16 | Build behind TLS proxies | Optional `extra_ca` build secret (empty by default, never in an image layer) | Needed in environments with TLS-inspecting proxies, including this one |
| 17 | Project deletion | `DELETE /projects/{id}` archives only | Permanent deletion arrives with the retention and deletion-marker work in R1 |
