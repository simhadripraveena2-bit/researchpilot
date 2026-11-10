# 2. System architecture

> **Amended by [doc 11](11-architecture-v2.md)** (Postgres-only queue, pgvector, Neo4j deferred, on-demand explanation service, domain events).

## 2.1 Runtime topology

```
                         ┌─────────────────────────────┐
  Browser  ── HTTPS ──▶  │  frontend (Vite build,      │
                         │  served by nginx)           │
                         └──────────────┬──────────────┘
                                        │ /api/v1 (REST + SSE)
                         ┌──────────────▼──────────────┐
                         │  api  (FastAPI, uvicorn)    │
                         │  - validation, CRUD, auth*  │
                         │  - enqueues runs            │
                         │  - streams run events (SSE) │
                         └───┬───────────┬─────────────┘
                   enqueue   │           │ read/write
                  (Redis)    │           │
             ┌───────────────▼──┐   ┌────▼────────────┐
             │ worker (arq)     │──▶│ PostgreSQL 16   │  structured record,
             │ - LangGraph runs │   │                 │  LangGraph checkpoints,
             │ - agents         │   └─────────────────┘  HTTP cache
             │ - integrations   │──▶ Qdrant (Phase 3+)   semantic retrieval
             │ - PDF pipeline   │──▶ GROBID (Phase 3+)   PDF → TEI
             │                  │──▶ Object storage      PDFs, TEI (local volume;
             │                  │                        S3-compatible later)
             │                  │──▶ Neo4j (Phase 7)     knowledge graph projection
             └───────┬──────────┘
                     │ HTTPS (rate-limited, cached)
     arXiv · Semantic Scholar · OpenAlex · Crossref · Unpaywall · Hugging Face · GitHub · LLM API
```

`*` auth deferred (decision D5).

**Why a separate worker:** research runs take minutes to hours, pause at human
checkpoints, and must survive restarts. The API process stays fast and
stateless; the worker owns long-running graphs. LangGraph's Postgres
checkpointer persists graph state at every step, so a run paused for approval
(or interrupted by a crash) resumes exactly where it stopped.

## 2.2 Backend layers

```
api/            HTTP: routers, request/response schemas, error mapping, SSE
workflows/      LangGraph graphs: state, nodes (thin), edges, checkpoints
agents/         Agent logic: typed input → typed output, no HTTP/DB knowledge
services/       Domain services: dedup, ranking, classification, report rendering,
                quote verification, entity normalisation
integrations/   One package per external source; all share a base HTTP client
processing/     PDF retrieval, GROBID/pdfium extraction, sectioning, chunking
llm/            LLMGateway, structured-output calls, prompt registry
db/             SQLAlchemy 2.0 models, Alembic migrations, repositories
domain/         Pydantic domain models shared across layers (Paper, Identifier,
                EvidenceSpan, Claim, …)
core/           settings, logging, errors, ids, clock
```

Dependency rule: `api → workflows → agents → services/integrations/llm →
domain`; `db` is reached only through repository interfaces injected into
nodes. Agents never import `db` or `api`, which keeps them unit-testable with
fakes.

## 2.3 Cross-cutting concerns

### Configuration
`pydantic-settings` reading environment variables (and `.env` in dev).
Groups: `DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, `GROBID_URL`,
`STORAGE_DIR`; per-source `S2_API_KEY`, `OPENALEX_API_KEY` (if required),
`CONTACT_EMAIL` (polite pools: OpenAlex, Crossref, Unpaywall), `GITHUB_TOKEN`,
`HF_TOKEN`; LLM `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `LLM_MODEL_DEFAULT`,
`LLM_MODEL_<AGENT>` overrides; rate-limit overrides per source. A
`/health/dependencies` endpoint reports which integrations are configured
(never the key values).

### HTTP client for integrations
One `SourceClient` base built on `httpx.AsyncClient`:
- **Rate limiting:** async token bucket per source (Redis-backed so multiple
  workers share the budget; in-memory fallback in tests). Defaults in doc 8.
- **Retries:** `tenacity` — retry on connect errors, 429, 500–504; exponential
  backoff with full jitter; honour `Retry-After`; max attempts configurable.
  No retry on other 4xx.
- **Circuit breaker:** after N consecutive failures a source is marked
  `degraded` for the rest of the run; the run continues with other sources and
  the report says so.
- **Caching:** `http_cache` table keyed by `sha256(method + normalised URL +
  sorted params + body)`; TTL per endpoint class (search 24 h, entity
  metadata 7 d, PDFs content-addressed and permanent). Cache hits are recorded
  in the run log as hits.
- **Provenance:** every successful response that produces records is stored in
  `source_records` (raw payload + hash + fetched_at) and linked to what it
  produced.
- **Identification:** a generic User-Agent `ResearchPilot/<version>` plus the
  configured contact email only where an API's polite pool asks for it.

### LLM gateway
- Interface: `async def generate_structured(task: str, prompt: PromptRef,
  inputs: dict, schema: type[BaseModel]) -> LLMResult[T]`.
- Anthropic implementation uses the SDK's structured output support
  (`client.messages.parse(...)` with the Pydantic schema), so the response is
  constrained to the schema and then validated again with Pydantic, plus
  **semantic validators** (paper IDs exist in the project, quotes verify,
  numeric values parse).
- Models: `claude-opus-5-5` default for all agents, overridable per agent.
  Effort set per task (e.g. `low` for query expansion, `high` for red-team).
- Refusals (`stop_reason == "refusal"`) and `max_tokens` truncation are
  handled explicitly: surfaced as agent errors, never treated as empty
  results. Server-side fallbacks enabled by default where available.
- Bulk extraction (Phase 3) can use the Message Batches API (asynchronous,
  lower cost) behind the same interface.
- Every call logs: agent, prompt id + version, model, input hash, token usage,
  latency, validation outcome. Prompts live as versioned files in the repo.
- Tests use a `FakeLLMGateway` returning fixture outputs keyed by prompt id.

### Logging and observability
`structlog` JSON logs with `run_id`, `project_id`, `agent`, `source`,
`request_id` bound as context. Secrets filtered by a processor. Per-run event
stream (`run_events` table + Redis pub/sub) powers the UI progress panel.
OpenTelemetry tracing is an optional later addition.

### Errors
Domain exceptions (`SourceUnavailable`, `RateLimited`, `FullTextUnavailable
(reason=…)`, `ValidationFailed`, `CheckpointRequired`) map to RFC 7807
`application/problem+json` at the API boundary. Inside a run, recoverable
errors are appended to `state.errors` and the run continues.

### Identity & IDs
UUIDv7 primary keys (time-ordered). External identifiers live in
`paper_identifiers` with a unique `(scheme, value)` constraint — this is the
database-level guard against duplicate papers.

## 2.4 Deduplication algorithm (Phase 2)

1. **Normalise identifiers:** DOI → lowercase, strip `https://doi.org/`;
   arXiv → strip version (`2401.01234v3` → `2401.01234`, keep version
   separately), handle old-style IDs (`cs/0101001`); S2 `paperId`, S2
   `corpusId`, OpenAlex `W…`, PMID, PMCID, DBLP key.
2. **Cross-reference:** S2 `externalIds` and OpenAlex `ids` give several
   identifiers per record; each record contributes all of them.
3. **Exact merge:** union-find over records sharing any identifier.
4. **Fuzzy merge (only for records without shared identifiers):** blocking
   key = first 3 normalised title tokens + year ±1; candidates must have title
   similarity ≥ 0.93 (token-sort ratio on NFKC-casefolded, punctuation-stripped
   titles) **and** matching first-author surname. Ambiguous pairs (0.85–0.93)
   are not merged; they are recorded as `possible_duplicate` for UI review.
5. **Preprint ↔ published version:** treated as one work (`paper`) when
   linked by an identifier source; the arXiv version and DOI version are both
   kept as identifiers, and `publication_date` / `venue` prefer the published
   version while `first_available_date` keeps the preprint date.
6. **Field resolution:** per-field precedence with provenance recorded in
   `papers.field_sources` (e.g. abstract: arXiv > S2 > OpenAlex > Crossref;
   venue: Crossref > OpenAlex > S2).
7. **Merging into existing DB papers** uses the same identifier lookup; merges
   are logged in `paper_merge_events` and reversible.

## 2.5 Ranking & classification (Milestone 1, deterministic)

- **Relevance score** = weighted sum, each component stored:
  BM25 over title+abstract vs. topic and approved queries; embedding cosine
  similarity (when embeddings enabled); number of distinct queries/sources that
  returned the paper; in-corpus citation connectivity.
- **Latest:** `publication_date` within window, relevance ≥ threshold, sorted
  by date.
- **Foundational:** in-corpus reference count (how many project papers cite
  it) ≥ k, or top percentile of log global citations among papers older than
  N years; reason string stored, e.g. "cited by 14 of 120 project papers;
  8,302 citations (OpenAlex, 2026-11-10)".
- **Related:** included papers that are neither.
- An optional LLM relevance screen (Phase 2, off by default) may only produce
  `include/exclude + reason + quote from abstract`; it never invents metadata.

## 2.6 Storage of files
`STORAGE_DIR/pdf/<sha256[:2]>/<sha256>.pdf` and `.../tei/<sha256>.tei.xml`.
Content-addressed, so the same PDF downloaded twice is stored once. An
S3-compatible adapter (MinIO) can replace the local volume later.

## 2.7 Deployment
- `docker-compose.yml`: `postgres`, `redis`, `api`, `worker`, `frontend`;
  profiles add `qdrant`, `grobid` (Phase 3) and `neo4j` (Phase 7).
- Multi-stage Dockerfiles; non-root users; healthchecks.
- Alembic migrations run by a one-shot `migrate` service before `api`/`worker`.
- GitHub Actions: lint, type-check, unit tests, integration tests with
  service containers, frontend tests, Docker build.
