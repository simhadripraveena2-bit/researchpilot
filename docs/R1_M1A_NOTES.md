# R1 M1a (Discover) implementation notes

Scope approved for this round: identifiers, SourceClient, arXiv / Semantic Scholar /
OpenAlex / Crossref / bioRxiv / medRxiv clients, paper manifestations, identifiers and source
records, deduplication and the Version Matcher, date events and the Date Resolver, and arXiv
announcement capture; then release types and date windows (task 4a) and the research
objective model and API (task 5, without the Planner) and the graph-compatible relationship
infrastructure (task 6a), and the deterministic Planner with discovery workflow W1 (task 6).
**Not** in this round: M1b–M1d (assessment, Latest Research, learning) and Neo4j. PostgreSQL is the only store; no Neo4j.

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
* HAS_VERSION scope enforcement (`enforce_relation_scope()` on `paper_manifestations`) needed
  `relation_registry`; added in task 6a (0009) without changing any existing data.

## First vertical slice: add an arXiv paper by identifier

`POST /api/v1/projects/{id}/papers {"identifier": "..."}` →
identifier parsing → `ArxivClient` (through `SourceClient`: shared rate limit, retries,
circuit breaker, HTTP cache, raw entry stored in `source_records`) → work + arXiv
manifestation + identifier + versions + author list + date events (each with reporting
source, upstream provenance, field path and source record) → Date Resolver → resolved date
on the work → `GET /projects/{id}/papers/{paper_id}` returns every event with its provenance.

Status: implemented and tested (see below). Steps 1–5 of the approved order are done; remaining M1a tasks are listed under Known limitations.

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

## Step 3: Version Matcher (D29)

| Part | Where | Tests |
|---|---|---|
| Pure matcher: decisive / strong / supporting / contradicting evidence, versioned rules (`d29-v1`) | `services/matching/version_matcher.py` | `tests/unit/test_version_matcher.py` (incl. Hypothesis: title similarity alone never matches; outcome symmetric) |
| Stated links per manifestation (arXiv author DOI, Crossref `relation`, bioRxiv/medRxiv `published`), derived index `paper_version_links` | `services/matching/links.py`, ingestion modules | integration tests below |
| Candidates (links in both directions + trigram-similar titles), decisions (`paper_match_decisions`), reversible merges (`paper_merge_events`), split, confirm/reject, sticky user decisions (trigger) | `services/matching/store.py`, migration `0005` | `tests/integration/test_version_matching.py` |
| Add-paper flow: ingest → follow decisive links (≤ 3, one level) → match → project membership on the surviving work | `services/papers/service.py` | all paper integration tests |
| API: `GET /projects/{id}/papers/{paper_id}/matches`, `POST /projects/{id}/matches/{decision}/confirm` / `reject`, `POST /projects/{id}/merges/{merge}/split` | `api/routers/papers.py` | `test_version_matching.py`, route inventory |

Real recorded cases (all in `test_version_matching.py`, `test_papers_biorxiv.py`, `test_papers_crossref.py`):

| Case | Result |
|---|---|
| bioRxiv `10.1101/2022.10.22.513336` ↔ eLife `10.7554/elife.87434` (and its versioned DOI `.3`), in either order | One work, three manifestations; first public appearance = verified bioRxiv posting 2022-10-22, not the 2024-06-03 journal date |
| medRxiv `10.1101/2023.12.14.23299828` ↔ JAMA Pediatrics `10.1001/jamapediatrics.2024.1379` (titles completely different) | Auto-matched by the stated link only (title similarity < 0.9) |
| arXiv `hep-th/9711200` → author DOI → IJTP reprint `10.1023/A:1026654312961` | Auto-matched; date `uncertain` (journal known only to the month, so `submission_only` does not apply) |
| Same paper's ATMP original and AIP proceedings version (same title and author, no identifier link) | Possible matches: listed with evidence, not merged; confirm merges, split restores exactly and is remembered as rejected |
| *Neural networks and logistic regression* Part I ↔ Part II (same authors, title similarity > 0.95) | No match (`part_number_differs`) |
| Two *Nature Reviews Methods Primers* records titled "Graph neural networks", one without authors | No match (author overlap cannot be established) |
| Comment `10.3390/insects17070712` ↔ reply `10.3390/insects17070713` | Related, not same; cannot be merged (422) |
| ResNet arXiv `1512.03385` ↔ CVPR `10.1109/cvpr.2016.90` (no identifier link yet) | Possible match until Semantic Scholar/OpenAlex evidence (step 4) |

## Step 4: Semantic Scholar and OpenAlex

| Part | Where | Tests |
|---|---|---|
| OpenAlex client: free work lookups, budgeted search, usage headers, budget-429 stop without retries, own daily cap, `basic`/`premium` capability switch (D24) | `integrations/openalex.py`, [integration doc](integrations/OPENALEX.md) | `tests/unit/test_aggregators.py` |
| Semantic Scholar client: Graph API lookup, optional `x-api-key`; without a key one attempt (429 has no `Retry-After`) | `integrations/semantic_scholar.py`, [integration doc](integrations/SEMANTIC_SCHOLAR.md) | same |
| `SourceClient`: per-source headers (API keys) and a provider-neutral `UsageBudget` hook | `integrations/base.py` | same |
| Enrichment after adding a paper: aggregator IDs, secondary `reported_publication_date` (upstream unknown), OpenAlex `index_created`/`metadata_updated`, "same record lists these identifiers" links (strong evidence); outcome per source returned as `coverage` | `services/papers/enrich.py`, `services/papers/service.py` | `test_papers_arxiv_slice.py`, `test_papers_biorxiv.py`, `test_version_matching.py` |
| Add by OpenAlex / Semantic Scholar ID (resolved to the DOI or arXiv ID of a system of record) | `services/papers/service.py` | `test_version_matching.py`, `test_papers_arxiv_slice.py` |

## Step 5: arXiv announcement capture and date resolution

| Part | Where | Tests |
|---|---|---|
| Feed client: announcement day from `pubDate` (US Eastern date), types and versions from `announce_type` / `guid`, empty feeds | `integrations/arxiv_feed.py`, [integration doc](integrations/ARXIV.md) | `tests/unit/test_arxiv_feed.py` |
| `arxiv_announcement_log` (as listed); `new` → primary `preprint_announced`, `replace` → `version_announced`; applied at capture and when a paper is ingested later; affected works re-resolved | migration `0006`, `services/dates/announcements.py`, `services/papers/ingest.py` | `tests/integration/test_arxiv_announcements.py` |
| Daily worker job, once per UTC day (`jobs.dedupe_key`, `enqueue_once`), categories from settings plus projects' arXiv works | `worker/main.py`, `jobs/queue.py` | same |

Real cases: `2611.13190` goes from `submission_only` (2026-11-09) to verified `announced`
(2026-11-11) with the submission event unchanged; `2604.22997`'s v2 replacement is a version
event and does not make the paper new; capture is idempotent; a failing feed is reported per
category and logs nothing.

## Semantic Scholar with the approved API key

| Part | Where | Tests |
|---|---|---|
| Key from `S2_API_KEY` (`SecretStr`), sent only as `x-api-key`; redacted from logs; never in errors, fixtures or Git | `core/settings.py`, `integrations/registry.py` | `test_semantic_scholar.py::test_the_key_never_appears_in_logs_or_errors` |
| One global limiter for every Semantic Scholar endpoint (`rate_limit_key = semantic_scholar`), 1.25 s minimum interval, shared by API and worker via Postgres | `integrations/semantic_scholar.py`, `integrations/base.py` | `test_semantic_scholar.py`, `test_s2_global_rate_limit.py` (two processes, three endpoints, real timing) |
| 429 handling: `Retry-After` honoured, otherwise jittered exponential backoff; the deferral applies to **all** processes (`RateLimiter.defer`); retries, cache, circuit breaker and graceful degradation kept | `integrations/base.py` | same |
| New endpoints: `/paper/search`, `/paper/{id}/references` (offset pagination) | `integrations/semantic_scholar.py` | `test_semantic_scholar.py` |
| Authenticated and unauthenticated modes | fixture transport serves authenticated recordings only when the header is sent | unit + `authenticated_client` integration tests |
| Real authenticated recordings replace the constructed fixture | `tests/fixtures/sources/semantic_scholar/` | ResNet arXiv ↔ CVPR merge test |
| Attribution requirements and website placement | [ATTRIBUTION.md](ATTRIBUTION.md) | — |

## Release types and date windows (task 4a)

What already existed and was reused: per-manifestation date events with provenance, the
Date Resolver (confidence, first public appearance, `submission_only`), announcement capture,
the Version Matcher, `users.timezone`. What was missing and is now built:

| Part | Where | Tests |
|---|---|---|
| Explicit publication type per manifestation (preprint, journal article, conference paper, …, correction, retraction, expression of concern); migration `0007` with backfill; notices detected from Crossref `update-to`/`updated-by`, linked to originals as related-not-same | `domain/enums.py`, `services/papers/ingest*.py`, `integrations/crossref.py`, migration `0007` | `test_releases.py` (real correction + retraction) |
| Windows: rolling 7 days `[now − 168 h, now)`, custom ranges as UTC days or offset instants, ≤ 366 days; date-only = UTC day with `boundary_day`; month/year never in windows ≤ 31 days | `domain/windows.py` | `tests/unit/test_windows.py` (R1-48 boundaries; property: zone never changes membership) |
| Local display: IANA zones with DST, abbreviations, date-only values never shifted; `tzdata` dependency so slim images have the zone database | `domain/windows.py` | DST transitions Europe (2026-10-25) and North America (2026-03-08, 2026-11-01), UTC+5:30, UTC+14 |
| Release-type classifier (new preprint, new publication, published version of an earlier preprint, revised version, correction notice, older paper newly indexed, date uncertain) | `services/dates/release_types.py`, `services/dates/releases.py` | `tests/unit/test_release_types.py` (30 cases incl. properties: later journal dates never make an announced preprint new; unconfirmed dates never promoted) |
| API: `GET /projects/{id}/releases` (window, counts, entries with local display), `GET/PUT /me/preferences` (display time zone), `?tz=` on paper detail | `api/routers/releases.py`, `api/routers/papers.py` | `tests/integration/test_releases.py` (14 cases on real records) |

Real cases: arXiv `2611.13190` → new preprint (announced 2026-11-11); `2604.22997` v2 →
revised version; bioRxiv → eLife: new preprint in Oct 2022, revised version in Mar 2023,
published version of an earlier preprint in Jun 2024 (never new research); Crossref correction
and retraction notices → correction notice; CVPR 2016 first seen now → older paper newly
indexed.

## Research objective model (task 5: model and API, no Planner)

Migration `0008`, `services/objectives/`, `api/routers/objectives.py`, page
`/projects/:id/objective`.

* **One objective per project, many versions.** `research_objectives` holds one immutable row
  per version (`UNIQUE(project_id, version)`); `projects.active_objective_id` says which
  version is in use (composite FK: always one of the project's own). Every edit, including a
  sub-question change, inserts the next version and makes it active; `activate` puts an
  earlier version back in use without creating or changing anything.
* **Contents:** main question, sub-questions, domain and subdomains, tasks and problem areas,
  keywords, synonyms, related (focus) concepts, exclusions, constraints (methods; datasets and
  benchmarks; compute, hardware, cost; time; resources; licences; other), expected outcomes,
  user context, notes, level, goal, source, `based_on_version`, `change_summary`, `created_by`.
  Lists are trimmed and deduplicated (case-insensitive, first spelling kept). New list-type
  fields need no new table (arrays/JSONB; the constraints schema is validated in the API).
* **Sub-questions** are rows of `objective_sub_questions` linked to exactly one version by
  `structural_relations` `PART_OF` (the approved single-source rule: no `objective_id`
  column). A new version copies them as new rows with the same keys; new sub-questions get the
  next key never used in the project, so `SQ3` always means the same sub-question in history.
* **Recorded objective version:** `research_runs.objective_version` (R0 column, now with a
  composite FK) and `project_items.objective_version` (new) are set from the active version
  when the row is created and cannot change afterwards (trigger). Relevance assessments and
  judgements (M1b) will reference the version's `id`, which never changes either.
* **Concurrency:** edits carry `base_version`, which must be the active version; the service
  locks the project row, so of two edits from the same base exactly one creates a version and
  the other gets **409** with the now-active version (`UNIQUE(project_id, version)` is the
  backstop).
* **Validation:** field limits (422) — main question 3–1000 chars, list items 1–300 chars,
  ≤ 50 per list, ≤ 6 sub-questions (RIE §2.1), sub-question keys `SQn`, no unknown fields; hard
  rules (422) — duplicate keys or texts, an exclusion that is also a keyword / concept / task /
  problem area, a dataset, benchmark or method both wanted and excluded/avoided. Completeness
  (saved anyway, reported on every read and by `/validate`): ≥ 2 sub-questions, a domain, a
  task or problem area, keywords or concepts, an expected outcome.
* **Authorization:** all routes are project-scoped (`ProjectScoped`, route-inventory test);
  other users' projects are 404; viewers can read and validate but not change (403).
* **Frontend:** a basic form (core fields; one item per line), version list, viewing an
  earlier version read-only with "Use this version", completeness hints and the 409 message.
  Synonyms and constraints are kept on save but edited only through the API for now.

## Relationship sources and graph data (task 6a)

Migration `0009`, `researchpilot/relations/` (registry, writer, audit, tombstones),
`services/projects/deletion.py`, alembic SQL in `alembic/rp_sql/relations_0009.py`.

**Relationship types and their single source** (database registry = code registry, tested):

| Type | Class | Source | Scope policy |
|---|---|---|---|
| CITES | research | `citations` | global only |
| AUTHORED_BY | research | `paper_authors` | global only |
| AFFILIATED_WITH | research | `author_affiliations` | global only |
| INTRODUCES / USES_METHOD / EVALUATES_ON | research | `entity_links` (by `role`) | project or global |
| EXTENDS / CONTRADICTS / RELATED_TO / ADDRESSES / DERIVED_FROM | research | `research_relations` (by `type`) | project or global |
| VALIDATED_BY | research | `research_relations` | project only |
| HAS_VERSION | structural | `paper_manifestations.paper_id` | global only (no scope column) |
| IN_PROJECT | structural | `project_items` | project only |
| PART_OF | structural | `structural_relations` | project only |
| REPORTS_LIMITATION (R2), RESULT_FOR (R2), IMPLEMENTED_BY (R4) | — | known to the code registry; registered with their source tables | — |

New node sources: `authors`, `research_groups` (global) and `entities` (global; label by
type; glossary terms are not nodes). New tables: `evidence_spans`, `relation_decisions`,
`relation_suppressions`, `relation_assertion_log`, `entity_tombstones`, `deletion_log`.

* **Database rules, for any writer** (the same triggers on every registered source, read
  from the registry): registered type and allowed endpoint combination; endpoints exist as
  graph nodes (composite FKs where endpoints are polymorphic); type and endpoints never
  change (except HAS_VERSION / IN_PROJECT moves by merge/split); deterministic
  `relation_uid` (UUIDv5, a forged one is refused); the project-scope invariant and the
  global-scope rule (no project context, no user assertions in global rows); evidence by
  assertion (source records and verified spans are looked up); sticky rejection (only a user
  in the row's project changes a rejected row; global rows are rejected only by system
  verification); rejected rows cannot be deleted except by cascade.
* **RelationWriter** (`relations/writer.py`) is the single write path, enforced by a source
  scan test. Callers pass a `WriteContext` (project or global; system service or user). It
  validates the same rules first (clear 422 `relation_rejected` errors), upserts by natural
  key (concurrent writers produce one row), never downgrades an assertion (a user's, or an
  established one by an inferred one), logs promotions (`quote_verified`), and turns
  automatic writes that hit a rejected row or a suppression fingerprint into logged no-ops.
  `reject` / `confirm`: project rows change (sticky); global rows get a project overlay
  (`relation_decisions`) plus a suppression and are never modified. `system_reject`
  (failed verification) and `retract` (source withdrew) for any scope. Structural writes:
  `link_part_of`, `add_to_project`, `move_versions`, `merge_project_items` /
  `split_project_items` (the objective, paper and matching services now call these).
* **Deletion markers:** triggers write `entity_tombstones (uid, kind, reason, timestamps)` for
  every deleted graph node and relationship row, for moved edges (`merge_split`, old uid) and
  for rejections and retractions; a marker is cleared when the element exists or becomes
  eligible again. Deleting a project or user sets the reason (`project_delete`,
  `account_delete`) for the whole cascade. `DELETE /projects/{id}?permanent=true` (owner)
  deletes the project, its outbox events and everything scoped to it, and writes a
  `deletion_log` entry (salted hash, counts). A daily `tombstone_purge` job removes markers
  verified absent or older than 30 days.
* **Audits** (`relations/audit.py`): `check_enforcement` (every registry row has its
  triggers, endpoint/scope columns with FKs, the global-only CHECK; a dummy type without
  triggers fails), `undeclared_references` (any reference column into a node table must be
  a registered relationship column, scope, or declared non-source), `find_orphans` (nodes
  without source rows, qualifying rows without nodes, kind or scope mismatches).
* **Reads:** the PostgreSQL `GraphService` now serves 1-hop neighbours with scope
  visibility, assertion policy and project overlays.

## Planner and discovery workflow W1 (task 6)

`services/discovery/` (planner, search, resolve, relate, summary, runs), `workflows/discovery.py`,
`api/routers/discovery.py`, migration `0010` (search log), page action "Find papers".

```
POST /projects/{id}/discovery-runs  (objective version recorded on the run)
  -> prepare : load that objective version -> Planner -> plan in run manifest, search_queries rows
  -> confirm : ◆ plain-language plan; rejected -> run cancelled, nothing searched
  -> search  : each (query, source) not yet succeeded -> source client (rate limit, retries,
               cache, circuit breaker) -> status + hits (search_results -> source_records)
  -> resolve : each pending hit -> no identifier | excluded | duplicate | beyond limit
               | ingest from system of record (arXiv / Crossref / bioRxiv / medRxiv;
                 S2/OpenAlex hits resolved to DOI or arXiv, attached as secondary records)
               -> decisive version links -> Version Matcher -> Date Resolver
               -> RelationWriter.add_to_project (run id + run's objective version)
  -> relate  : CITES among stored works from OpenAlex referenced_works (RelationWriter,
               global, source_metadata, evidence = the record)
  -> summary : manifest.discovery.summary; succeeded | partially_succeeded | failed
```

* **Planner** (deterministic, `rules-1`): core query from the main question; one query per
  sub-question anchored on the main topic; expansions while the budget lasts (synonyms,
  tasks/problem areas, concepts, preferred/required methods, datasets/benchmarks). The user's
  own phrases stay whole (also in plural). arXiv queries use `AND`/`OR` groups and `ANDNOT`
  for exclusions; other sources get plain text and exclusions are applied to the hits'
  titles and abstracts. Avoided methods and excluded datasets/benchmarks flag hits instead of
  dropping them. Compute, time and resource constraints are listed as not applied. The plan
  records why each source is or is not used (bioRxiv/medRxiv: no topic search). `plan_id` is a
  hash of the content: the same objective version and options always give the same plan.
* **Sources:** arXiv (`search_query`, relevance), Crossref (`query`, `sort=relevance`, no
  cursor - see decision 61), Semantic Scholar (`/paper/search`), OpenAlex (`/works?search=`).
  A source failing twice in a run is not asked again in that run; an exhausted OpenAlex
  budget stops OpenAlex at once. Hits are stored as source records first.
* **Nothing is invented:** a hit without a DOI or arXiv ID is recorded (`no_identifier`) and
  not ingested; aggregator metadata never becomes a primary date; possible matches are only
  recorded (shown in the summary for review); CITES only between works we hold, from the
  source's own reference list.
* **Durability and idempotency:** plan, search log and hit outcomes are committed as they
  happen; LangGraph checkpoints after each node. After a crash the run resumes at its node
  and skips what is recorded (tested by crashing mid-resolve); a retry (`POST /runs/{id}/retry`)
  re-sends only failed or skipped searches and re-reads only failed hits.
* **Cancellation:** `WorkflowDeps.ensure_not_cancelled` is checked before every search, before
  the arXiv prefetch and before every hit, outside the hit transactions; the `relate` and
  `summary` steps check it on entry. A cancelled run keeps every committed outcome, leaves the
  remaining hits `pending` (never marked failed or excluded because of the cancel), writes no
  citations and no summary, and stays `cancelled` (the retry endpoint refuses it with 409).
  Tested by cancelling between searches, before the prefetch and after two works were added.
* **Recorded end-to-end fixtures:** `scripts/record_discovery_fixtures.py` ran the workflow
  for `tests/fixtures/discovery.py` against the real APIs on 2026-11-12 and saved every
  response (arXiv and Crossref answered everything; Semantic Scholar answered one query and
  was rate limited on two; OpenAlex's daily budget was exhausted). CI replays them.

## Evaluation benchmarks: G-MATCH and G-LATEST-DATES (B0)

| Part | Where | Tests |
|---|---|---|
| Case, dataset and split models; protocol guard (case IDs per split, expert labels for B1–B3, no synthetic data outside B0, B3 only outside the repository and only for the custodian); work-hash overlap check | `evaluation/cases.py` | `tests/unit/test_evaluation_cases.py` |
| Replay of recorded responses (shared with the test fixtures); B0-only recording of missing system-of-record responses | `evaluation/replay.py`, `tests/fixtures/source_transport.py` | all integration tests |
| Harness: scratch database, production code paths, unavailable aggregators, not-evaluable detection | `evaluation/harness.py` | `tests/integration/test_benchmarks_b0.py` |
| G-MATCH runner and metrics (both orders, split + re-match for reversibility and sticky rejection) | `evaluation/gmatch.py` | same + unit metric tests |
| G-LATEST-DATES runner and metrics | `evaluation/gdates.py` | same |
| Reports (Markdown + JSON, run metadata, B3 aggregate-only) | `evaluation/report.py`, `scripts/run_benchmarks.py` | `test_b3_report_is_aggregate_only` |
| B0 datasets (52 + 43 real cases, AI-proposed labels) and their recordings | `backend/benchmarks/` (`build_b0.py` generates the JSON) | — |
| Guidelines, B3 isolation proposal, reports | `docs/evaluation/` | — |

Run: `uv run python scripts/run_benchmarks.py benchmarks/g_match/b0.json
benchmarks/g_latest_dates/b0.json --admin-url <postgres admin URL>`.

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
| 18 | No-identifier auto-match | Disabled: such pairs are at most possible matches | The rule needs abstract similarity from embeddings (≥ 0.90), which arrive with M1b; until then a human confirms |
| 19 | Contradictions | A contradicting feature (Part I/II, comment/reply/erratum markers on one side, thesis vs article, disjoint authors, different first author without an identifier link, implausible date order) blocks auto-match **and** possible match; with decisive evidence it gives a possible match | Adversarial pairs should not even be proposed as "possibly the same work" |
| 20 | Merge representation | `papers.merged_into_id`; the merged work's row and graph node stay; its manifestations and all their rows move to the older (surviving) work; `paper_merge_events.moved` records manifestation ids and project memberships, so a split is exact | Reversibility (R1-46) without deleting identities |
| 21 | `paper_version_links` (new table) | Derived index of links stated in source records, per manifestation | Finds candidate pairs in both directions; rebuildable from `source_records` |
| 22 | Following links | After adding a paper, the targets of its decisive links are fetched (one level, at most 3, failures only reduce coverage) | Makes preprint ↔ journal pairs appear without a separate search |
| 23 | Earlier unconfirmed version (resolver) | If another manifestation has a secondary public claim > 2 days before every primary event, the date is `conflicting` (ARCHITECTURE §4.8.3 updated) | Found with the bioRxiv-outage case: otherwise the 2024 journal date would have been "verified" for a work public since 2022 |
| 24 | Strong links | Crossref `is-same-as` / `is-version-of` / `has-version` and (step 4) "both identifiers on one S2/OpenAlex record" are strong, not decisive | ARCHITECTURE §4.8a lists only preprint relations as decisive |
| 25 | Semantic Scholar without a key | One attempt, reported `unavailable` | Keyless requests always got 429 without `Retry-After` (with the approved key, see the section above) |
| 34 | Global 429 deferral | A 429 from any source pushes back the shared slot for every process, by `Retry-After` or by backoff (capped at 120 s) | Retrying processes must not each keep hitting a limited source |
| 35 | S2 minimum interval | 1.25 s (approved limit 1 request/s across all endpoints) | Margin for clock and network jitter; 429s still occur occasionally and are handled |
| 26 | OpenAlex without a key | Entity lookups (free) used; metered queries stop on the budget 429 and are refused until the reset; never retried | The keyless budget is shared per IP and was already used up |
| 27 | OpenAlex filled-in dates | `YYYY-MM-01` → month precision, `YYYY-01-01` → year precision | Verified: missing parts are filled with 01 |
| 28 | Aggregator IDs and dates | Attached to the looked-up manifestation (published DOI first); an ID already held by another work is not duplicated - the listing link lets the matcher compare the works | Both aggregators merge versions; their data is never primary |
| 29 | Effect on arXiv papers | OpenAlex reports a publication date for almost every arXiv paper; under the approved rule (a public claim of any kind rules out `submission_only`) such papers are `single_source` / unconfirmed until a primary event exists - which announcement capture (step 5) provides | Consequence of the corrected `submission_only` rule, now visible |
| 30 | Cross-listings | `cross` / `replace-cross` never produce announcement events | Verified: they can list old papers |
| 31 | `new` with a version > 1 | `preprint_announced` (version recorded in the evidence) | The first announcement of a paper replaced before it was announced |
| 32 | Capture schedule | Once per UTC day after 06:00 UTC via the job queue (`jobs.dedupe_key`), not a separate scheduler | The feed is rebuilt ~05:00 UTC and keeps no history; no new infrastructure (§4.8.5) |
| 33 | Categories | Configured list plus primary categories of projects' arXiv works | Objective-based category mapping arrives with M1c |
| 36 | Correction notice | New release type `correction_notice` (and publication types correction/retraction/expression of concern) | Requested; notices are never research and must not appear as new publications |
| 37 | Release types computed on read | `GET /projects/{id}/releases` classifies from stored events each time; no new table | Classification depends only on stored events and the window; snapshots and "Reclassified" badges belong to Latest Research scans (M1c, `latest_scan_entries`) |
| 38 | Custom ranges | UTC calendar days or offset timestamps; the user's zone is display-only | EVALUATION §3.8 / R1-47: results must be identical whatever the zone |
| 39 | New publication with a known earlier preprint | *Date uncertain*, not *New publication* | §4.8.4 requires that no earlier manifestation is known; covers the approved Nov 8 / Nov 15 case |
| 40 | Unconfirmed first date | Revision / newly indexed only with primary evidence of existence before the window; otherwise *Date uncertain* | Nothing unconfirmed is promoted; a v2 still proves an older v1 when v1 is primary-dated |
| 41 | `/me/preferences` | Display time zone (IANA, validated); allow-listed in the route inventory as user-level | ARCHITECTURE §4.11 contract |
| 42 | Version rows immutable | No UPDATE on objective versions, sub-questions or `PART_OF` rows; DELETE only through a cascade | History must not be rewritten silently (requirement 4) |
| 43 | Active version | `projects.active_objective_id` (composite FK), not an `is_active` flag | One pointer per project: no "two active" state to guard; activation never touches version rows |
| 44 | `project_items.objective_version` | New column (not in DATABASE_SCHEMA before) | Discovered items must say which objective version found them; `discovered_in_run_id` alone is null for manual adds |
| 45 | `relation_endpoint_rules.child_table` | Extra column | The generic cardinality and cascade triggers need the child's table; avoids hard-coding table names per rule |
| 46 | `parent_project` registration | The sub-question's node is created by its `PART_OF` insert, with the parent's scope; `rp_register_graph_node` no longer raises for that rule (0001 text restored on downgrade) | Scope comes from the parent, which is only known when the link is written |
| 47 | Stale run versions on (re)upgrade | 0008 clears `research_runs.objective_version` values that cannot refer to an objective (possible only after a downgrade); its downgrade clears them too | Found by the migration test: the composite FK could not be added otherwise |
| 48 | Edits without changes | 200 with the active version, no new version | Avoids empty history entries from repeated saves |
| 49 | Removed sub-question keys | Never reused in the project | A key in an old run or judgement keeps one meaning |
| 50 | Worker clock | `Worker` takes the existing injectable `Clock` for its daily capture scheduling | `test_capture_is_idempotent_and_runs_once_per_day` failed on the real date 2026-11-12 (the worker scheduled "today" from the wall clock) |
| 51 | Raw author lists | Renamed `paper_authors` → `manifestation_authors` (node data of the manifestation); new `paper_authors` is AUTHORED_BY | The old table held per-manifestation raw names with an always-empty `author_id`; as the AUTHORED_BY source it would have been a second, unresolved author link per version |
| 52 | No `citations.first_seen_run_id` | Not added | A run belongs to a project; a global relationship must not reference project context (the requested rule "global-only relationships must not contain project-specific evidence") |
| 53 | Sources of later releases | `limitations` (REPORTS_LIMITATION), RESULT_FOR and `item_code_links` (IMPLEMENTED_BY) are in the code registry, not created | Their endpoint node tables (limitations with evidence, reported results, repositories) are R2/R4; creating empty node tables now would be unnecessary |
| 54 | `entity_links` assessment roles | `compares_against`, `reports_metric` are scope-checked like the table's types but never projected and have no registry type | DATABASE_SCHEMA lists them as RIE data in the same table; a registry row would make them graph relationships |
| 55 | Trigger context | Acting user/service, scope and change/deletion reasons reach the triggers as transaction-local settings (`rp.actor`, `rp.actor_scope`, `rp.change_reason`, `rp.deletion_reason`) set by `RelationWriter` / deletion code | Lets one generic trigger enforce sticky rejection and write meaningful markers and log entries; direct SQL that forges a setting is outside the supported write path (the source scan blocks it in code) |
| 56 | `relation_assertion_log` | Adds `relation_uid`, statuses, `actor` and `scope_project_id` (FK, cascade) | Project history must be deleted with its project; status changes (retraction) are logged too |
| 57 | Neighbours in R1 | `GraphCapability.NEIGHBORS` advertised; citation graph, versions and related papers still not | Overlays must be applied by a real read path; the other views need data that the discovery workflow (task 6) fills |
| 58 | `evidence_spans` | Created now; `document_id` / `section_id` without FKs until documents exist (M1d) | Evidence by assertion needs span verification in the database |
| 59 | Markers on re-creation | A marker is removed when the same uid exists or is eligible again (re-insert, un-reject, move back) | Otherwise a later sync could delete a live element |
| 60 | Deletion log hash | HMAC-SHA256 with `DELETION_LOG_SALT`; without it a random salt is used and discarded | A one-way hash even when no salt is configured; never the raw id |
| 61 | Crossref topic search | `query` + `sort=relevance`, first page only, no `cursor` | Verified 2026-11-12: with `cursor=*` Crossref ignores relevance (`search-terms: null`) and returns unrelated works ("Low Molecular Weight Heparin" for a GNN query) |
| 62 | Planner | Deterministic rules, no LLM | Requested for this milestone; testable and reproducible. The LLM Planner of AGENT_DESIGN (drafting objectives) is not built; this is its rule-based fallback |
| 63 | Plan storage | In the run manifest (`discovery.plan`), not a table | One plan per run, read with the run; the search log holds everything queryable |
| 64 | `search_results` key | `PK(query_id, rank)`, `item_id` nullable, `outcome` | A hit must be recorded before it becomes a work, and also when it never does |
| 65 | Hit resolution | DOI first for aggregator hits (as when adding by identifier); arXiv hits by arXiv ID; arXiv IDs from aggregators fetched in one batch | Same system-of-record rule as manual adds; arXiv allows one request per 3 s |
| 66 | Items keep the run's objective version | `add_to_project(objective_version=...)` | An edit during the run must not change what the run's items record |
| 67 | One active discovery run per project | 409 on a second start | Two runs would race for the same items and sources |
| 68 | Not in W1 yet | Stage A, seed selection, citation expansion, the paper-set review checkpoint | They need the RIE (M1b) |
| 69 | Retry of finished runs | `failed` / `partially_succeeded` discovery runs can be reopened (`queued`) | Partial source failure is expected (rate limits, budgets); a retry redoes only what failed |
| 70 | Nominal issue dates | Crossref `published-print` with day 01, and `issued` with day 01 that does not equal the online/posted date, are stored with **month** precision (evidence note "nominal") | Found by G-LATEST-DATES B0 (GD-B0-034..036): print dates of 1 Nov 2018 / 1 Mar 2026 for articles online on 19 Nov / 30 Apr were verified as first public dates, and a print-only 1 Feb 2017 date (record created in July) was verified. Day 01 of an issue is the issue's nominal date. Conservative: a true day-01 print date now needs another day-precision event to be verified (as OpenAlex day-01 values already are) |
| 71 | Benchmark harness | Cases run the production paths (`add_paper_by_identifier`, capture, classifier, split) on a scratch database from recorded responses; aggregators without a recording answer 503 (unavailable); fresh source clients per case | No mocks of the rules under test; a circuit breaker opened by one case must not change the next (it did: GM-B0-015 lost Semantic Scholar evidence when run after other cases) |
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

## Known limitations (after steps 1–5 and tasks 4a, 5, 6 and 6a)

* **Semantic Scholar** works with the approved key; without `S2_API_KEY` it is reported
  `unavailable`. Even with the key, occasional 429s occur at 1.25 s spacing; they are retried
  with a global backoff and can make a call report `unavailable`. The standard API licence
  covers internal non-commercial research/education; a public site may need an expanded
  licence (see ATTRIBUTION.md).
* **OpenAlex** keyless budget is shared per IP and was used up from this environment: list
  queries stop until midnight UTC; single-work lookups still work.
* **Unannounced arXiv papers** with an OpenAlex date are `single_source` (unconfirmed), not
  `submission_only`, under the approved rule; announcement capture fixes this only from the day
  capture runs (feeds keep no history).
* The no-identifier auto-match needs abstract embeddings (M1b); such pairs are possible matches.
* Announcement capture categories come from settings and projects' arXiv works until M1c.
* Release types are computed on read; there are no snapshots, so a reclassification is not
  flagged as such until Latest Research scans (M1c) store entries.
* "No earlier preprint found in" lists the sources whose records the work has; it does not run a
  new search for an earlier preprint (scans in M1c do).
* Corrections are recognised from Crossref `update-to`; notices without it (e.g. some
  publishers, other registries) are classified by their type only.
* The frontend has no `LocalTime` component or Latest Research page yet (M1c); the API already
  returns the local display strings.
* **Objective:** objectives are entered by the user (`source = user_edit`); the Planner turns
  them into search plans but does not draft objectives (no LLM). Relevance is not assessed
  yet (M1b).
* **Discovery:** results are kept in source rank order, not assessed (M1b): no tiers, no
  citation expansion, no review of the paper set. The candidate limit counts distinct works.
* Exclusions on Semantic Scholar hits use the title only (the search does not return
  abstracts; adding the field would change every recorded request).
* Planner queries are keyword-based; a question phrased with rare words can produce queries
  that find little on arXiv's AND search (the plan and its results are shown so the user sees
  this).
* CITES is written only from OpenAlex reference lists of OpenAlex hits; S2 references are not
  fetched (one request per paper at 1 request/s).
* Release types in the summary use our first-seen date for works first seen in the run, so
  older works show as "newly indexed (first seen by ResearchPilot)", as designed.
* The objective page edits the core fields only; synonyms and constraints are API-only.
* **Relationships:** discovery writes IN_PROJECT, HAS_VERSION (through ingestion) and CITES
  (OpenAlex metadata); authorship and affiliations (author resolution), entity links
  (extraction, R2) and relevance relations (M1b) arrive with their workflows.
* Deletion markers are written but not consumed until the Graph Sync Worker (R2); until then
  markers are purged at the 30-day cap without verification (no alert, nothing to verify).
* Only project and account cascades set their own marker reason; other deletions default to
  `user_delete` (conversation/retention reasons arrive with those features).
* `signal_ids` in evidence are checked for presence only (assessment signals arrive in M1b).
* Account deletion (all of a user's projects) has no API yet; the database writes
  `account_delete` markers if a user row is deleted.
* No `objective.updated` reassessment consumer: the `objective.version_created` /
  `objective.activated` events are emitted but nothing consumes them until M1b.
* **Benchmarks:** only B0 exists, with **AI-proposed labels** (not gold, awaiting team
  review). B1/B2 need expert annotators and B3 a custodian (D19 roles not yet assigned).
  B0 sizes (52 match pairs, 43 date cases) are below the §2a targets (~100 each), and some
  categories are thin or missing (see `docs/evaluation/reports/`).
* Not started (outside this round): M1b–M1d, Neo4j.
