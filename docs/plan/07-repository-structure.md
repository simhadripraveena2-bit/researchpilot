# 7. Repository structure

Monorepo; backend and frontend are independently buildable.

```
researchpilot/
├── README.md
├── LICENSE                          # to be chosen (affects D2)
├── .env.example                     # every variable, documented, no secrets
├── .gitignore
├── Makefile                         # dev, test, lint, migrate, fmt, up/down
├── docker-compose.yml               # postgres, redis, api, worker, frontend
├── docker-compose.override.yml      # dev: hot reload, exposed ports
├── .github/
│   └── workflows/
│       ├── backend.yml              # ruff, mypy, pytest unit + integration
│       ├── frontend.yml             # eslint, tsc, vitest, build
│       └── e2e.yml                  # compose up + Playwright (fixtures mode)
├── docs/
│   ├── plan/                        # this plan
│   ├── adr/                         # architecture decision records (one per D#)
│   ├── integrations/                # one page per external API (limits, fields, quirks, verified date)
│   ├── data-model.md                # generated ERD + table docs
│   └── runbook.md                   # operating, backups, re-indexing
│
├── backend/
│   ├── pyproject.toml               # uv-managed; ruff, mypy, pytest config
│   ├── uv.lock
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── prompts/                     # versioned prompt templates (YAML/Jinja) + schemas refs
│   │   ├── planner/query_plan.v1.yaml
│   │   └── …
│   ├── src/researchpilot/
│   │   ├── main.py                  # FastAPI app factory
│   │   ├── core/                    # settings.py, logging.py, errors.py, ids.py, clock.py
│   │   ├── domain/                  # Pydantic domain models
│   │   │   ├── paper.py             # PaperRecord, CanonicalPaper, Author
│   │   │   ├── identifiers.py       # DOI/arXiv/… parsing & normalisation
│   │   │   ├── evidence.py          # EvidenceSpan, Claim, ClaimKind
│   │   │   ├── run.py               # RunConfig, RunStatus, SourceStatus
│   │   │   └── report.py            # structured report models
│   │   ├── db/
│   │   │   ├── base.py, session.py
│   │   │   ├── models/              # SQLAlchemy models by area
│   │   │   └── repositories/        # ProjectRepo, PaperRepo, RunRepo, …
│   │   ├── integrations/
│   │   │   ├── base/                # SourceClient, rate_limit.py, retry.py, cache.py, circuit.py
│   │   │   ├── arxiv/               # client.py, parser.py (Atom), mapper.py, README.md
│   │   │   ├── semantic_scholar/
│   │   │   ├── openalex/
│   │   │   ├── crossref/
│   │   │   ├── unpaywall/           # Phase 3
│   │   │   ├── huggingface/         # Phase 5
│   │   │   ├── github/              # Phase 5
│   │   │   └── registry.py          # SourceRegistry: enabled sources from settings
│   │   ├── services/
│   │   │   ├── dedup.py             # union-find + fuzzy matcher
│   │   │   ├── enrichment.py
│   │   │   ├── ranking.py           # BM25, scoring components
│   │   │   ├── classification.py    # latest/foundational/related
│   │   │   ├── quote_verifier.py    # Phase 3
│   │   │   ├── entity_normalizer.py # Phase 3
│   │   │   └── reports/             # builders + renderers (md, bibtex, csv, latex later)
│   │   ├── processing/              # Phase 3: pdf_resolver.py, downloader.py, grobid.py, pdfium.py, sections.py, chunking.py, embeddings.py
│   │   ├── llm/
│   │   │   ├── gateway.py           # LLMGateway protocol + LLMResult
│   │   │   ├── anthropic_gateway.py
│   │   │   ├── fake.py              # deterministic test gateway
│   │   │   └── prompts.py           # prompt registry/loader with versions
│   │   ├── agents/
│   │   │   ├── base.py              # Agent protocol, AgentContext, AgentResult
│   │   │   ├── planner/             # agent.py, schemas.py
│   │   │   ├── discovery/
│   │   │   ├── citation/
│   │   │   ├── analysis/            # Phase 3
│   │   │   ├── methodology/         # Phase 4
│   │   │   ├── datasets/
│   │   │   ├── metrics/
│   │   │   ├── gaps/
│   │   │   ├── novelty/
│   │   │   ├── proposal/
│   │   │   └── red_team/
│   │   ├── workflows/
│   │   │   ├── state.py             # ResearchState + reducers
│   │   │   ├── checkpoints.py
│   │   │   ├── discovery_graph.py
│   │   │   ├── analysis_graph.py    # Phase 3
│   │   │   ├── intelligence_graph.py# Phase 4
│   │   │   └── report_graph.py      # Phase 6
│   │   ├── worker/                  # arq worker settings, job functions, run lifecycle
│   │   └── api/
│   │       ├── deps.py
│   │       ├── errors.py            # problem+json handlers
│   │       ├── sse.py
│   │       ├── schemas/             # request/response models (separate from domain)
│   │       └── routers/             # health, projects, runs, checkpoints, papers, search, reports
│   └── tests/
│       ├── conftest.py
│       ├── fixtures/
│       │   ├── http/                # recorded API responses per source (sanitised)
│       │   ├── llm/                 # recorded structured outputs per prompt id
│       │   └── papers/              # small open-licence PDFs for Phase 3
│       ├── unit/                    # mirrors src tree
│       ├── integration/             # Postgres/Redis via testcontainers or compose
│       ├── workflows/               # graph runs with scripted checkpoints
│       ├── contract/                # live API contract checks (opt-in: pytest -m live)
│       └── eval/                    # extraction quality evaluation (Phase 3+)
│
└── frontend/
    ├── package.json, tsconfig.json, vite.config.ts, tailwind.config.ts
    ├── Dockerfile                   # build → nginx
    ├── nginx.conf                   # SPA + /api proxy
    ├── src/                         # see 06-frontend.md §6.6
    └── e2e/                         # Playwright specs
```

## Tooling standards

- Python 3.12, `uv`, `ruff` (lint + format), `mypy --strict` for `domain`,
  `services`, `agents`, `integrations`, `workflows`; `pytest`, `pytest-asyncio`,
  `respx` (HTTP mocking), `hypothesis`, `testcontainers` (or compose services in CI).
- Node 20 LTS, `pnpm`, ESLint, Prettier, `tsc --noEmit`.
- Pre-commit hooks for ruff, prettier, end-of-file, secret scanning (gitleaks).
- Conventional commits; ADRs for each architecture decision.
