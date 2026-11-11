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

## Step 1: Crossref

| Part | Where | Tests |
|---|---|---|
| Crossref client: DOI lookup, cursor-paginated search, JATS stripping, partial dates, relations | `integrations/crossref.py`, [integration doc](integrations/CROSSREF.md) | `tests/unit/test_crossref.py` |
| Ingestion: published / preprint / other manifestations, one event per Crossref date field with field-path evidence; bioRxiv/medRxiv records secondary with upstream from `institution` | `services/papers/ingest_crossref.py` | `tests/integration/test_papers_crossref.py` |
| Add by DOI (non-arXiv DOIs go to Crossref) | `services/papers/service.py` | same |
| Resolver tie-break: on equal dates, the specific event beats Crossref's derived `issued` | `services/dates/resolver.py` | `test_date_resolver.py` |

## Step 2: bioRxiv and medRxiv

| Part | Where | Tests |
|---|---|---|
| Client per server: `/details` by DOI (all versions), interval pages with offset cursors, `/pubs` links; "no posts found" = not found; shared request budget for the host | `integrations/biorxiv.py`, [integration doc](integrations/BIORXIV.md) | `tests/unit/test_biorxiv.py` |
| Ingestion: preprint manifestation, primary v1 `preprint_posted`, v2+ `version_posted`, versions table; same DOI from Crossref joins the same manifestation as secondary events | `services/papers/ingest_biorxiv.py` | `tests/integration/test_papers_biorxiv.py` |
| Routing: `10.1101/YYYY.MM.DD.N…` DOIs → likely server, then the other, then Crossref (also when the API is down: date stays unconfirmed) | `services/papers/service.py` | same, `test_papers_crossref.py` |
| `SourcePolicy.rate_limit_key`: several sources on one host share a request budget | `integrations/base.py` | `test_biorxiv.py` |

## Decisions and deviations

| # | Topic | What was done | Why |
|---|---|---|---|
| 1 | arXiv `updated` | Stored as `version_submitted` of the latest version, not `metadata_updated` | Verified: it is the latest version's submission time (integration doc) |
| 2 | `submission_only` vs. "`preprint_submitted` can never be the first public event" (DATABASE_SCHEMA §14) | The trigger allows `preprint_submitted` as the first public event **only** with basis `submission_only`, from the arXiv API v1, when the work has no public-availability claim at all (correction 1 below) | The two rules contradicted each other; §14 now states this rule |
| 3 | `paper_versions` key | `(manifestation_id, version)` plus `paper_id` | Versions belong to a manifestation; a work can have arXiv and bioRxiv versions |
| 4 | Authors | `paper_authors` per manifestation with raw names; `author_id` empty until author resolution; `authors` table not created yet | Author identity needs S2/OpenAlex author IDs or ORCID; creating author nodes from raw names would create false identities |
| 5 | `papers.embedding` | Not created yet | The embedding model is chosen with M1b signals |
| 6 | Corroboration | Only from public-availability events (not bare "publication date" claims) | The first public event must be a public-availability event (§14 trigger) |
| 7 | Secondary agreement | Claims within ±1 day agree; further apart = `conflicting` | §4.8.3 defines ±1 day for corroboration and 2 days only for primary conflicts |
| 8 | Cross-process rate limit | New table `source_rate_limits` (atomic slot reservation) | API and worker are separate processes; an in-process bucket could exceed arXiv's limit |
| 9 | Retries | Implemented in `SourceClient` (no `tenacity` dependency) | Small, fully tested, deterministic with an injected clock |
| 10 | Adding a paper | Synchronous in the API request (one source call, rate-limited) | Manual add is a single lookup; discovery runs go through the worker (W1) |
| 11 | Capability errors | New `GraphCapabilityUnavailable` keeps the code `graph_capability_unavailable`; other features use `capability_unavailable` | R0 mapped every capability error to the graph code |
| 13 | Crossref `accepted` on preprints | Not recorded as `accepted` for `posted-content` | It is the latest preprint version's date (verified), not a journal acceptance |
| 14 | Crossref `created` | Stored as `index_created` | Registration of the DOI record in Crossref; never a public-availability event |
| 15 | Upstream of Crossref dates | `crossref` for DOIs it registers; `biorxiv`/`medrxiv` for those servers' preprints (from `institution`) | Crossref exposes the depositing server; agreement with the server's own API is therefore not independent corroboration |
| 16 | bioRxiv/medRxiv request rate | 1 request/s shared by both servers | No published limit; one host |
| 17 | Preprint server outage | Falls back to Crossref so the paper can still be added, with an unconfirmed date | Coverage over failure; the date is never overstated |
| 12 | Network access | A personal `researchpilot` cloud environment allows only the six source hosts | Required to verify source behaviour; CI uses recorded responses only |

## Corrections after review of 7f447bc

| # | Issue | Fix | Tests |
|---|---|---|---|
| 1 | The Date Resolver put the `submission_only` fallback in the same pool as real public events and took the earliest, so an unannounced arXiv submission (Nov 8) beat a journal's online publication (Nov 15) | The fallback applies only when the work has **no public-availability claim** of any kind: no primary or secondary announcement, posting, online, issue or issued v1 event and no reported publication date, at any precision, on any manifestation (claims more than a day in the future are ignored). Otherwise primary events decide, then the normal secondary rules (`corroborated`, `source_agreement`, `single_source`, `conflicting`); a public claim known only to the month or year gives `uncertain`. When a primary public event wins over an earlier submission, the reason says that an earlier arXiv submission exists. The submission event is never changed or deleted. Migration `0004` aligns the first-public trigger (`submission_only` refused whenever such a claim exists); its downgrade restores the 0003 rule | `test_date_resolver.py`: journal after unannounced submission; OpenAlex-only date after submission (`single_source`); two secondary sources (`source_agreement`); month-precision issue (`uncertain`); future and metadata dates do not block the fallback. `test_papers_arxiv_slice.py`: the trigger refuses `submission_only` once a journal `published_online` event exists, re-resolving selects the journal event, and the submission row is byte-for-byte unchanged |
| 2 | `cache_key()` ignored the endpoint class, so the same URL and parameters requested as a search (1 h TTL) and an entity lookup (12 h TTL) shared one entry and one expiry | The key is now (source, endpoint class, URL, sorted parameters); behaviour within one endpoint class is unchanged. Existing entries under the old key format simply stop matching and expire | `test_source_client.py`: same URL under `search` and `entity` gives two entries; after 2 h the entity entry still hits and the search entry is refetched; key is independent of parameter order |

Both regression suites fail on 7f447bc and pass after the fix.

## Doc issues found (resolved)

* ARCHITECTURE §4.8.2 listed arXiv `updated` as a metadata date (deviation 1): corrected;
  `version_submitted` now names arXiv `updated` as its source.
* DATABASE_SCHEMA §14 contradicted §4.8.4 on `preprint_submitted` (deviation 2): §14 now
  allows it only as the `submission_only` event under the rule above, and lists the
  basis/event pairs the trigger enforces.
* ARCHITECTURE §4.8.4 (and §4.8.5, §10) now state that `submission_only` applies only when no
  other public-availability event is known, with the Nov 8 / Nov 15 example.
