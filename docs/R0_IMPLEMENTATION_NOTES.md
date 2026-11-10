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
  `GraphView`. R0 advertises no traversal capabilities: direct-neighbour traversal returns
  `graph_capability_unavailable` (available from R1) and multi-hop paths likewise (R2).
- Journey registry with the nine stages and one next step.
- Frontend shell (Vite, React 18, TypeScript, Tailwind, TanStack Query, React Router):
  dashboard, three-field new-project form, project overview with journey bar, system-check
  run view with live progress and a confirm/stop checkpoint.
- Docker images (backend, frontend/nginx), Compose stack (postgres+pgvector, migrate, api,
  worker, frontend, grobid; all ports on 127.0.0.1), frontend and stack CI workflows.

## R0 acceptance tests

| Test | Where | Status |
|---|---|---|
| R0-1 `make up` from a clean clone, all services healthy | `make up`, `.github/workflows/stack.yml` | pass locally and on GitHub (see CI results); the CI smoke test covers readiness and project creation, the full system-check run was verified locally |
| R0-2 readiness 200 / problem+json 503 | `tests/integration/test_api.py` | pass |
| R0-3 SSE streaming, checkpoint pause, worker restart, resume | `tests/integration/test_runs_e2e.py` | pass (incl. crash mid-step) |
| R0-3 cancellation and retry limit (review fixes) | `tests/integration/test_run_lifecycle.py` | pass |
| R0-4 rolled-back events never dispatched; idempotent retries | `tests/integration/test_outbox.py` | pass |
| R0-5 secrets never logged | `tests/unit/test_logging.py` | pass |
| R0-6 migrations up/down/up; models match migrations | `tests/integration/test_migrations.py` | pass |
| R0-7 nine stages, deterministic states, one next step | `tests/unit/test_journey.py`, `test_api.py` | pass |
| R0-8 provider independence (fake swap, lint rule, manifest) | `test_llm_config.py`, `test_import_rules.py`, `test_runs_e2e.py` | pass |
| R0-9 project scope on every route; no non-local bind without auth | `test_route_inventory.py`, `test_security.py`, `test_api.py` | pass |
| R0-10 graph readiness (registration, conditions, immutability, GraphService, lint) | `test_graph_readiness.py`, `test_graph_capabilities.py`, `test_api.py`, `test_import_rules.py` | pass |

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

## Review fixes (before R0 sign-off)

| # | Finding | Fix | Tests |
|---|---|---|---|
| 1 | A running job could overwrite a CANCELLED run with SUCCEEDED | Every run status transition (`mark_running`, `open_checkpoint`, `finish`, the queued update on a decision) is a conditional update that applies only while the run is not terminal. Workflows check for cancellation at every progress event and step boundary (`RunCancelled`); the worker heartbeat checks the run and interrupts the job's task when the run was cancelled, then completes the job without retry. Cancelling also closes pending checkpoints (`rejected`, "run cancelled"); deciding a checkpoint of a finished run returns 422 | `test_run_lifecycle.py`: cancel while a step executes, cooperative stop without the heartbeat, terminal runs cannot change state, cancel while awaiting approval |
| 2 | Stale running jobs were reclaimed regardless of `attempts < max_attempts` | `claim()` reclaims a stale job only while attempts remain. Each worker tick calls `fail_exhausted_stale()`, which marks exhausted stale jobs `failed` ("worker stopped responding; retry limit reached") and fails their runs with error type `WorkerLost` (a cancelled run stays cancelled) | `test_run_lifecycle.py`: three simulated hard crashes, no fourth claim, job and run end failed with a `run.failed` event; exhausted job does not override a cancelled run |
| 3 | R0 graph service advertised NEIGHBORS but returned only the requested node | `PostgresGraphService.capabilities()` is empty in R0; `neighbors()` raises `CapabilityUnavailable` (`capability=neighbors`, `available_from=R1`), returned as 501 problem+json `graph_capability_unavailable` | `test_graph_capabilities.py`, `test_api.py::test_neighbour_traversal_is_unavailable_until_r1` |
| 4 | Stack CI only ran on pushes to `main` | `stack.yml` runs on pushes to every branch (plus pull requests and manual runs) | Stack workflow run below |
| 5 | Frontend CI installed pnpm 9; `package.json` declares pnpm 10.28.0 | `pnpm/action-setup` reads the version from `frontend/package.json` (`package_json_file`) | Frontend workflow run below |

## CI results

All three workflows pass on commit `b220319` (2026-11-10):

| Workflow | Result | Run |
|---|---|---|
| backend (ruff, format, mypy --strict, 81 tests against PostgreSQL) | pass | [42922233594](https://github.com/simhadripraveena2-bit/researchpilot/actions/runs/42922233594) |
| frontend (pnpm 10.28.0 from `package.json`, typecheck, 4 tests, production build) | pass | [42922233601](https://github.com/simhadripraveena2-bit/researchpilot/actions/runs/42922233601) |
| stack (clean `docker compose up --build --wait`: all services healthy; smoke test through nginx: readiness, create project) | pass | [42922233803](https://github.com/simhadripraveena2-bit/researchpilot/actions/runs/42922233803) |

The first stack runs on GitHub exposed two Compose problems that did not show locally, both
fixed: the default empty build CA pointed at `/dev/null`, which the Compose builder refuses to
read without `--allow` (now `docker/no-extra-ca.crt`, an empty file in the project); and the
GROBID image's JDK crashed reading the runner's cgroup v2 layout (now
`JAVA_TOOL_OPTIONS=-XX:-UseContainerSupport`). Failed runs, for the record:
[42921168576](https://github.com/simhadripraveena2-bit/researchpilot/actions/runs/42921168576), [42921374192](https://github.com/simhadripraveena2-bit/researchpilot/actions/runs/42921374192).

## Remaining limitations

- **Cancellation granularity.** Cancellation is cooperative: a running step stops at its next
  progress event or step boundary, or when the worker heartbeat (every
  `JOB_HEARTBEAT_SECONDS`, 5 s by default) sees the cancellation and interrupts the job's
  task. Code that does not yield to the event loop (CPU-bound or blocking calls) cannot be
  interrupted until it returns; whatever it does afterwards can no longer change the run's
  state. Long blocking work in later releases must run in a cancellable subprocess or check
  for cancellation itself.
- **Side effects after cancellation.** Conditional transitions protect the run's state, not
  other writes a step may already have made. R0's only workflow (system check) has none;
  workflows from R1 must make their writes idempotent and scoped to the run, as already
  required by the architecture.
- **Retry limit after crashes.** A crashed job is detected after `JOB_STALE_AFTER_SECONDS`
  (30 s by default), so a run whose worker dies on its last attempt fails about 30 s later.
- **Anthropic adapter** not run against the live API (no key in this environment; D1 open).
- **Frontend API types** are hand-written until OpenAPI generation in R1.
