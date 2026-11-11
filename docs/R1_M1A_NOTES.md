# R1 M1a (Discover) implementation notes

Scope approved for this round: identifiers, SourceClient, arXiv / Semantic Scholar /
OpenAlex / Crossref / bioRxiv / medRxiv clients, paper manifestations, identifiers and source
records, deduplication and the Version Matcher, date events and the Date Resolver, and arXiv
announcement capture. **Not** in this round: the research objective model and Planner (task 5),
the discovery workflow W1 (task 6), graph-compatible relationship tables (task 6a), and
M1b–M1d. PostgreSQL is the only store; no Neo4j.

## Dependencies

```
identifiers ─┬─> SourceClient ─> clients (arXiv, S2, OpenAlex, Crossref, bioRxiv/medRxiv)
             │                        │
             └─> paper tables (works, manifestations, identifiers, versions, source records)
                         │            │
                         │            ├─> date events ─> Date Resolver ─> release types
                         │            │                       ^
                         │            └─> arXiv announcement capture (RSS) ─┘
                         └─> dedup (identifier union) ─> Version Matcher (needs ≥ 2 sources)
```

* The Version Matcher needs at least two sources that describe the same work differently
  (arXiv plus Crossref or Semantic Scholar), so it follows the second client.
* The Date Resolver's confidence rules are pure and were built first; release types and
  window logic need announcement events and published-version manifestations.
* Announcement capture needs works with arXiv manifestations to attach events to.
* HAS_VERSION scope enforcement (`enforce_relation_scope()` on `paper_manifestations`) needs
  `relation_registry` (task 6a). The manifestation table already has no scope column and is
  registered as a global node source, so adding the check later changes no data.

## First vertical slice: add an arXiv paper by identifier

`POST /api/v1/projects/{id}/papers {"identifier": "..."}` →
identifier parsing → `ArxivClient` (through `SourceClient`: shared rate limit, retries,
circuit breaker, HTTP cache, raw entry stored in `source_records`) → work + arXiv
manifestation + identifier + versions + author list + date events (each with reporting
source, upstream provenance, field path and source record) → Date Resolver → resolved date
on the work → `GET /projects/{id}/papers/{paper_id}` returns every event with its provenance.

Status: implemented and tested (see below).

## What exists

| Part | Where | Tests |
|---|---|---|
| Identifier parsing (DOI, arXiv old/new + versions, S2 paper/corpus, OpenAlex, PMID, PMCID; URLs) | `domain/identifiers.py` | `tests/unit/test_identifiers.py` (incl. Hypothesis property tests) |
| `SourceClient` (rate limit, Retry-After, backoff, circuit breaker, HTTP cache, source records) | `integrations/base.py` | `tests/unit/test_source_client.py`, rate limiter in `test_papers_arxiv_slice.py` |
| arXiv API client | `integrations/arxiv.py`, [integration doc](integrations/ARXIV.md) | `tests/unit/test_arxiv_parse.py` (recorded responses), `tests/live/test_arxiv_live.py` (opt-in) |
| Tables: `source_records`, `http_cache`, `source_rate_limits`, `papers`, `paper_manifestations`, `paper_identifiers`, `paper_dates`, `paper_versions`, `paper_source_links`, `paper_authors`, `project_items` | migration `0003`, `db/models/{sources,papers}.py` | `test_migrations.py`, `test_graph_readiness.py` |
| First-public invariant trigger (DATABASE_SCHEMA §14) | migration `0003` | `test_papers_arxiv_slice.py` |
| Date Resolver (confidence rules, flags) | `services/dates/resolver.py`, `store.py` | `tests/unit/test_date_resolver.py` |
| Ingestion and API | `services/papers/`, `api/routers/papers.py` | `tests/integration/test_papers_arxiv_slice.py` |

## Decisions and deviations

| # | Topic | What was done | Why |
|---|---|---|---|
| 1 | arXiv `updated` | Stored as `version_submitted` of the latest version, not `metadata_updated` | Verified: it is the latest version's submission time (integration doc) |
| 2 | `submission_only` vs. "`preprint_submitted` can never be the first public event" (DATABASE_SCHEMA §14) | The trigger allows `preprint_submitted` as the first public event **only** with basis `submission_only`, from the arXiv API, when no announcement is captured | The two rules contradict each other; this keeps §4.8.4's labelled fallback and forbids every other use |
| 3 | `paper_versions` key | `(manifestation_id, version)` plus `paper_id` | Versions belong to a manifestation; a work can have arXiv and bioRxiv versions |
| 4 | Authors | `paper_authors` per manifestation with raw names; `author_id` empty until author resolution; `authors` table not created yet | Author identity needs S2/OpenAlex author IDs or ORCID; creating author nodes from raw names would create false identities |
| 5 | `papers.embedding` | Not created yet | The embedding model is chosen with M1b signals |
| 6 | Corroboration | Only from public-availability events (not bare "publication date" claims) | The first public event must be a public-availability event (§14 trigger) |
| 7 | Secondary agreement | Claims within ±1 day agree; further apart = `conflicting` | §4.8.3 defines ±1 day for corroboration and 2 days only for primary conflicts |
| 8 | Cross-process rate limit | New table `source_rate_limits` (atomic slot reservation) | API and worker are separate processes; an in-process bucket could exceed arXiv's limit |
| 9 | Retries | Implemented in `SourceClient` (no `tenacity` dependency) | Small, fully tested, deterministic with an injected clock |
| 10 | Adding a paper | Synchronous in the API request (one source call, rate-limited) | Manual add is a single lookup; discovery runs go through the worker (W1) |
| 11 | Capability errors | New `GraphCapabilityUnavailable` keeps the code `graph_capability_unavailable`; other features use `capability_unavailable` | R0 mapped every capability error to the graph code |
| 12 | Network access | A personal `researchpilot` cloud environment allows only the six source hosts | Required to verify source behaviour; CI uses recorded responses only |

## Doc issues found

* ARCHITECTURE §4.8.2 lists arXiv `updated` as a metadata date (deviation 1).
* DATABASE_SCHEMA §14 contradicts §4.8.4 on `preprint_submitted` (deviation 2).
