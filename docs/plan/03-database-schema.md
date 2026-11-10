# 3. Database schema

> **Amended by [doc 11 §11.6](11-architecture-v2.md#116-database-schema-changes)** (claim kinds v2, learning tables, persistence tables, outbox).

PostgreSQL 16 is the system of record. Qdrant holds embeddings that point back
to Postgres IDs. Neo4j (Phase 7) is a *projection* rebuilt from Postgres, never
the source of truth.

Conventions: UUIDv7 `id` primary keys; `created_at`/`updated_at timestamptz`;
`jsonb` only for genuinely variable payloads; enums as Postgres enums (or
check constraints) managed by Alembic. Tables are grouped by the phase that
introduces them.

## 3.1 Entity overview

```
projects ─┬─< research_runs ─┬─< agent_executions
          │                  ├─< run_events
          │                  ├─< checkpoints
          │                  └─< search_queries ─< search_results >─ papers
          ├─< project_papers >──────────────────────────────────────┘
          ├─< claims ─< claim_evidence >─ evidence_spans
          └─< reports

papers ─┬─< paper_identifiers         (UNIQUE scheme,value  ← dedup guard)
        ├─< paper_authors >─ authors
        ├─< paper_source_links >─ source_records   (raw API payloads)
        ├─< citations (citing / cited)
        ├─< documents ─< document_sections ─< evidence_spans
        ├─< paper_entity_mentions >─ entities  (method/dataset/metric/task…)
        ├─< reported_results
        └─< limitations
```

## 3.2 Phase 1–2 tables (Milestone 1)

### projects
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid null | reserved for auth (D5) |
| title | text not null | |
| topic | text not null | user's topic / problem statement, verbatim |
| description | text | |
| settings | jsonb | defaults for runs (sources, windows, limits, auto-approve flags) |
| status | enum `active, archived` | |
| created_at, updated_at | timestamptz | |

### research_runs
| column | type | notes |
|---|---|---|
| id | uuid PK | also LangGraph `thread_id` |
| project_id | uuid FK | |
| workflow | enum `discovery, analysis, intelligence, report` | |
| status | enum `queued, running, awaiting_approval, succeeded, partially_succeeded, failed, cancelled` | `partially_succeeded` = some sources/papers failed |
| config | jsonb | full resolved config snapshot (reproducibility) |
| manifest | jsonb | code version (git sha), prompt versions, model IDs, source API versions |
| started_at, finished_at | timestamptz | |
| error | jsonb | problem detail if failed |

### agent_executions
One row per agent invocation inside a run.
`id, run_id, agent, node, status, input_hash, output jsonb, error jsonb,
llm_calls int, tokens_in int, tokens_out int, started_at, finished_at`.

### run_events
Append-only progress log for the UI and audit.
`id bigserial, run_id, ts, level, agent, event_type, message, data jsonb`.

### checkpoints (human approvals)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK | |
| name | text | e.g. `approve_query_plan`, `review_paper_set` |
| payload | jsonb | what the human is asked to review |
| status | enum `pending, approved, modified, rejected` | |
| decision | jsonb | edits made by the human (e.g. removed queries) |
| decided_at | timestamptz | |
| comment | text | |

### search_queries
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK | |
| source | enum `arxiv, semantic_scholar, openalex, crossref, …` | |
| query_text | text | exact string sent |
| params | jsonb | filters (year range, fields, sort) |
| origin | enum `user, planner_llm, rule_expansion, gap_probe, novelty_probe` | why the query exists |
| rationale | text | planner's stated reason, if any |
| status | enum `pending, succeeded, failed, skipped` | |
| result_count | int | |
| total_available | int null | source-reported total hits |
| error | jsonb | reason code + message |
| executed_at | timestamptz | |
| cache_hit | bool | |

### search_results
`query_id FK, paper_id FK, rank int, source_record_id FK, PRIMARY KEY (query_id, paper_id)`
— records exactly which query surfaced which paper at which rank.

### source_records (raw provenance + cache of entity payloads)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| source | enum | |
| source_entity_id | text | e.g. S2 paperId, OpenAlex W-id, arXiv id |
| endpoint | text | |
| payload | jsonb | raw response object for this entity |
| payload_sha256 | text | |
| fetched_at | timestamptz | |
| UNIQUE | (source, source_entity_id, payload_sha256) | identical refetches deduplicate |

### papers (canonical works)
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| title | text not null | |
| normalized_title | text | for fuzzy matching (GIN trigram index) |
| abstract | text null | |
| abstract_status | enum `available, unavailable, restricted` | |
| publication_date | date null | best known (published version preferred) |
| publication_date_precision | enum `day, month, year` | |
| first_available_date | date null | earliest version (e.g. arXiv v1) |
| year | int null | |
| venue | text null | |
| publication_type | text null | journal-article, preprint, proceedings… |
| is_open_access | bool null | |
| language | text null | |
| fields_of_study | text[] | as reported by sources |
| citation_counts | jsonb | `{"openalex": {"count": 812, "as_of": "…"}, "semantic_scholar": {…}}` |
| field_sources | jsonb | which source supplied each canonical field |
| metadata_level | enum `stub, metadata, full_text` | stubs = known only as citation targets |
| created_at, updated_at | timestamptz | |

### paper_identifiers
`paper_id FK, scheme enum(doi, arxiv, s2_paper, s2_corpus, openalex, pmid,
pmcid, dblp, mag, acl), value text, version text null, source enum,
UNIQUE (scheme, value)`.

### paper_merge_events
`id, surviving_paper_id, merged_paper_id, method enum(identifier, fuzzy,
manual), evidence jsonb, created_at, reverted_at null` — merges are auditable
and reversible.

### possible_duplicates
`paper_a, paper_b, similarity numeric, reason, status enum(open, merged,
dismissed)`.

### authors / paper_authors
`authors: id, display_name, normalized_name, orcid null, s2_author_id null,
openalex_author_id null` (unique partial indexes on each external ID).
`paper_authors: paper_id, author_id, position int, raw_name, raw_affiliations jsonb,
PRIMARY KEY (paper_id, position)`.

### paper_source_links
`paper_id, source_record_id, PRIMARY KEY (both)`.

### citations
| column | type | notes |
|---|---|---|
| citing_paper_id | uuid FK | |
| cited_paper_id | uuid FK | |
| sources | text[] | which APIs reported this edge |
| is_influential | bool null | S2 flag, if available |
| intents | text[] | S2 citation intents, if available |
| contexts | jsonb | citation context snippets with source |
| first_seen_run_id | uuid | |
| PRIMARY KEY | (citing_paper_id, cited_paper_id) | |

### project_papers (a paper's role within a project)
| column | type | notes |
|---|---|---|
| project_id, paper_id | PK | |
| status | enum `candidate, included, excluded` | |
| roles | text[] | `latest`, `foundational`, `related`, `seed` |
| role_reasons | jsonb | human-readable reason + numbers per role |
| relevance_score | numeric | |
| relevance_components | jsonb | BM25, embedding sim, query hits, connectivity |
| discovered_via | enum `search, reference, citation, recommendation, manual, gap_probe` | |
| discovered_in_run_id | uuid | |
| discovered_from_paper_id | uuid null | for citation-expanded papers |
| exclusion_reason | text null | |
| is_saved | bool | "Saved Papers" |
| tags | text[] | user tags |
| user_note | text | |
| first_seen_at, updated_at | timestamptz | |

### reports
`id, project_id, run_id, report_type enum(paper_discovery, literature_review,
proposal, …), version int, content jsonb (structured sections with claim/paper
IDs), rendered_markdown text, paper_set_hash text, created_at`. Reports are
immutable snapshots; regenerating creates a new version.

### http_cache
`key text PK, source, url, status int, headers jsonb, body bytea|jsonb,
fetched_at, expires_at`. Large bodies (PDFs) are not stored here; they go to
object storage via `documents`.

## 3.3 Phase 3 tables (deep analysis)

### documents
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| paper_id | uuid FK | |
| kind | enum `pdf, tei, html, plain_text` | |
| source_url | text | where it was fetched from |
| location_source | enum `arxiv, s2_oa, openalex_oa, unpaywall, user_upload` | |
| license | text null | as reported by the OA location |
| version | text null | arXiv version / accepted / published |
| sha256 | text | content address |
| storage_uri | text | |
| page_count | int | |
| retrieval_status | enum `retrieved, unavailable, failed` | |
| failure_reason | enum `no_oa_location, http_error, not_a_pdf, too_large, parse_failed, license_restricted, timeout` | |
| failure_detail | text | e.g. "HTTP 403 from publisher host" |
| parser | text | `grobid-0.8.x`, `pdfium` |
| retrieved_at | timestamptz | |

### document_sections
`id, document_id, ordinal, heading, section_type enum(abstract, introduction,
related_work, method, experiments, results, discussion, limitations,
conclusion, appendix, references, other), page_start, page_end, text,
char_offset_start` (offsets within the document's canonical extracted text).

### evidence_spans
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| paper_id | uuid FK | |
| document_id | uuid FK null | null when the evidence is the abstract/metadata |
| section_id | uuid FK null | |
| location_kind | enum `abstract, body_text, table, figure_caption, metadata` | |
| page | int null | 1-based |
| char_start, char_end | int null | offsets into canonical text |
| bbox | jsonb null | GROBID coordinates for highlighting |
| quote | text not null | verbatim text |
| verified | bool not null | quote located in source text |
| created_by | text | agent/extractor name + version |

### entities
`id, type enum(task, method, architecture, algorithm, dataset, benchmark,
metric, model, library), canonical_name, aliases text[], description,
external_refs jsonb (HF dataset id, GitHub repo, …), UNIQUE (type,
canonical_name)`.

### paper_entity_mentions
`id, paper_id, entity_id, role enum(proposes, uses, compares_against,
evaluates_on, reports_metric, extends), evidence_span_id FK not null,
extraction_run_id, confidence numeric`.

### paper_contributions
`id, paper_id, contribution_type enum(method, dataset, benchmark, analysis,
theory, system, survey), summary text, evidence_span_id not null`.

### reported_results
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| paper_id | uuid FK | paper that reports the number |
| method_entity_id | uuid FK | |
| dataset_entity_id | uuid FK | |
| metric_entity_id | uuid FK | |
| value | numeric null | parsed value |
| value_text | text not null | exactly as printed |
| unit | text null | |
| split | text null | test/val/… |
| setting | text null | e.g. "5-shot", "zero-shot" |
| is_own_method | bool | authors' method vs. baseline re-reported |
| evidence_span_id | uuid FK **not null** | no evidence, no row |
| extraction_run_id | uuid | |

### limitations
`id, paper_id, text, category enum(data, scale, generalization, evaluation,
compute, assumptions, reproducibility, ethics, other), stated_by enum(authors,
inferred), evidence_span_id not null, extraction_run_id`.

### claims / claim_evidence (generic traceable statements)
`claims: id, project_id, run_id, kind enum(reported_result,
extracted_observation, ai_synthesis, ai_hypothesis), text, created_by_agent,
subject_type, subject_id, status enum(active, superseded, rejected)`.
`claim_evidence: claim_id, evidence_span_id null, paper_id null, relation
enum(supports, contradicts, context), note` — check constraint: at least one
of evidence_span_id / paper_id.

## 3.4 Phase 4 tables (research intelligence)

- `research_directions`: `id, project_id, run_id, label, description,
  method jsonb (clustering algorithm + params), paper_ids uuid[]` plus
  `direction_papers(direction_id, paper_id, membership_score)`.
- `taxonomy_nodes`: `id, project_id, parent_id, label, definition,
  entity_ids uuid[]` (methodology taxonomy tree).
- `limitation_clusters`: `id, project_id, label, limitation_ids uuid[],
  distinct_paper_count, distinct_author_group_count`.
- `gap_candidates`: `id, project_id, run_id, kind enum(recurring_limitation,
  sparse_intersection, conflicting_results, missing_evaluation), description,
  signal jsonb (the computed numbers), source_ids jsonb, status
  enum(candidate, probed, addressed_by_existing_work, open, rejected)`.
- `gap_probes`: `id, gap_id, search_query_ids uuid[], top_matches jsonb
  (paper ids + overlap judgements with quotes), conclusion enum(no_close_match,
  partial_overlap, already_addressed), probed_at`.
- `hypotheses`: `id, project_id, gap_id, statement, rationale,
  expected_outcome, falsification_criteria, status enum(draft, under_review,
  survived, revised, rejected), version`.
- `hypothesis_reviews` (red-team): `id, hypothesis_id, reviewer_agent,
  verdict enum(survives, needs_revision, reject), objections jsonb (each with
  type, argument, evidence ids), counter_evidence_paper_ids uuid[]`.
- `hypothesis_scores`: `hypothesis_id, novelty, significance, feasibility,
  evidence_strength, overall, components jsonb (each with explanation and
  evidence ids), scoring_version`.
- `novelty_checks`: `id, hypothesis_id, query_ids uuid[], sources text[],
  nearest_papers jsonb, result enum(no_close_match_found, similar_work_found,
  inconclusive), checked_at`.
- `experiment_plans`: `id, hypothesis_id, datasets uuid[], metrics uuid[],
  baselines uuid[], protocol jsonb, compute_estimate jsonb, risks jsonb`.

## 3.5 Phase 5–7 tables

- `code_repositories`: `id, host, owner, name, url, stars, license,
  last_pushed_at, archived, fetched_at` and `paper_code_links(paper_id,
  repo_id, link_source enum(paper_text, hf_paper_page, github_search,
  manual), is_official bool null, evidence_span_id null)`.
- `hf_artifacts`: `id, kind enum(model, dataset, space), hf_id, metadata
  jsonb, fetched_at` and `paper_hf_links(paper_id, artifact_id, link_source)`.
- `monitors` (scheduled updates): `id, project_id, schedule cron, query_ids,
  last_run_at, enabled`.
- `project_memory`: `id, project_id, kind (decision, note, preference),
  content, created_at`.

## 3.6 Key indexes and constraints

- `paper_identifiers (scheme, value)` UNIQUE — dedup guard.
- `papers.normalized_title` GIN `gin_trgm_ops`; `papers (year)`;
  `papers (publication_date)`.
- `project_papers (project_id, status)`, `(project_id, is_saved)`.
- `citations (cited_paper_id)` for reverse lookups.
- Full-text search: generated `tsvector` on `title || abstract` with GIN
  index (Paper Explorer search, BM25-ish ranking via `ts_rank_cd`; exact BM25
  computed in the service layer for runs).
- `evidence_spans (paper_id)`, `reported_results (dataset_entity_id,
  metric_entity_id)` for benchmark tables.

## 3.7 Qdrant collections (Phase 3; optional in Phase 2)

| collection | point id | vector | payload |
|---|---|---|---|
| `paper_abstracts` | paper_id | title+abstract embedding | project_ids, year, has_full_text |
| `document_chunks` | chunk uuid | chunk embedding | paper_id, document_id, section_id, page, char_start, char_end, section_type |
| `limitations` | limitation_id | limitation text embedding | paper_id, category |

Embedding model name + version stored in collection metadata; changing the
model creates a new collection rather than mixing vectors.

## 3.8 Neo4j model (Phase 7)

Nodes: `Paper, Author, Method, Dataset, Metric, Task, Direction, Gap,
Hypothesis, Repository`. Relationships: `CITES, AUTHORED, PROPOSES, USES,
EVALUATED_ON, REPORTS{value, metric}, BELONGS_TO, ADDRESSES, CHALLENGES,
IMPLEMENTS`. Every relationship carries `evidence_span_id` / `pg_id` so the UI
can jump back to the evidence. A sync job projects from Postgres
incrementally (by `updated_at`).
