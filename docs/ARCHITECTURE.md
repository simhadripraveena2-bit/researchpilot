# Architecture

**Status:** canonical. It consolidates `docs/plan/02`, `docs/plan/08` and
`docs/plan/11`, which are kept as history.

## 1. Architectural principles

| # | Principle | Consequence |
|---|---|---|
| A1 | **One research record** | Every feature reads and writes the same Postgres tables. No feature keeps a private copy of papers or entities |
| A2 | **Everything assessable is a research item** | Papers, entities (methods, datasets, metrics, models…), repositories, gaps and ideas share a `research_items` supertype, so assessments, overrides, feedback and notes use one mechanism with real foreign keys |
| A3 | **Audience and objective are parameters** | One pipeline per capability, not one per user level |
| A4 | **Two execution modes** | Durable batch workflows (LangGraph, worker) for multi-step jobs. On-demand, cached, streamed generation (API) for explanations and cards |
| A5 | **Signals before judgement** | Deterministic signals for everything; LLM judgements for a bounded top-K or on demand; all with provenance |
| A6 | **Claims are typed and validated in one place** | A single `ClaimValidator` serialises every AI-produced statement |
| A7 | **Domain events (outbox)** | Staleness, recomputes, monitoring and alerts are event consumers, added without changing producers |
| A8 | **Declarative journey** | The nine stages are a registry. Readiness is derived from data, never stored |
| A9 | **Swappable infrastructure behind interfaces** | `JobQueue`, `VectorStore`, `GraphService`, `LLMGateway`, `ObjectStore` |
| A10 | **Graph-ready from day one; Neo4j as the long-term knowledge graph** | Every entity has a stable UUID and every relationship carries assertion, confidence, evidence and provenance. PostgreSQL stays the source of truth; Neo4j (from R2) is a synchronised graph read model behind `GraphService` (§12) |

## 2. Runtime topology (MVP)

```
Browser ──▶ frontend (React SPA via nginx)
               │  /api/v1  REST + SSE (+ streamed explanation responses)
               ▼
            api (FastAPI)
              ├─ routers / auth (disabled for local use; required for hosting, §11)
              ├─ Journey service (stage registry)
              ├─ Explanation service (on-demand, cached)
              ├─ Intelligence read service (cards, tiers, overrides, feedback)
              └─ ClaimValidator
               │ enqueue (Postgres job queue)        LISTEN/NOTIFY for progress
               ▼
            worker
              ├─ LangGraph workflows (discovery, assessment, learning setup,
              │   analysis, investigation, experiment design, proposal, monitor)
              ├─ Intelligence engine (signals, scoring, tiers)
              └─ Event consumers (staleness, recompute, impact detection)
               │
   ┌───────────┼──────────────┬──────────────────────┐
   ▼           ▼              ▼                      ▼
PostgreSQL   GROBID       File storage          External APIs
+ pgvector   (PDF→TEI)    (PDF/TEI/LaTeX,       arXiv · Semantic Scholar · OpenAlex ·
                          content-addressed)    Crossref · Unpaywall · HF · GitHub · LLM
```

**Five containers in the MVP:** `postgres` (with pgvector), `grobid`, `api`,
`worker`, `frontend`. **Neo4j joins in R2 as a required service**: the research knowledge graph
(§12). Deferring it is a sequencing decision: R0–R1 build the graph-ready
model and run graph queries through the PostgreSQL implementation of
`GraphService`. Redis and Qdrant are optional scaling adapters (§9).

## 3. Backend modules

```
researchpilot/
  core/          settings, logging, errors, ids, clock, budgets
  domain/        Pydantic models: items, papers, identifiers, evidence, claims,
                 objective, assessment, card, journey
  db/            SQLAlchemy models, Alembic migrations, repositories
  integrations/  base SourceClient (rate limit, retry, cache, circuit breaker,
                 provenance) + arxiv, semantic_scholar, openalex, crossref,
                 unpaywall, biorxiv (bioRxiv + medRxiv), huggingface, github
  processing/    pdf resolver, downloader, grobid client, arXiv LaTeX source,
                 sectioning, chunking, embeddings
  intelligence/  ← Research Intelligence Engine
                 signals/ (plugins per item type and dimension)
                 scoring.py, tiers.py, profiles.py, overrides.py,
                 feedback.py, cards.py, staleness.py
  services/      dedup + version matcher, enrichment, field_map, glossary, learning_path,
                 comparison tables, conflict detection, report builder,
                 quote_verifier, claim_validator, citation_validator,
                 dates/ (date resolver, release-type classifier),
                 latest/ (scan planner, related-paper linker, digest assembly),
                 retrieval/ (evidence retriever: hybrid pgvector + full-text),
                 tutor/ (context builder, scope router, conversation memory,
                 teaching plans, learning progress, retention)
  llm/           LLMGateway, Anthropic implementation, fake gateway,
                 prompt registry (versioned files)
  agents/        LLM-backed agents (see AGENT_DESIGN)
  graph/         GraphService interface, relation registry, projector,
                 sync worker, reconciler; adapters/postgres, adapters/neo4j (R2)
                 (the Neo4j driver is imported only in adapters/neo4j)
  workflows/     LangGraph graphs and shared state
  journey/       stage registry, readiness rules, next-step logic
  events/        outbox writer, dispatcher, consumers
  worker/        job definitions, scheduling
  api/           routers, request/response schemas, SSE, problem+json
```

Dependency rule: `api → workflows/services → agents/intelligence →
integrations/llm/processing → domain`. Agents and signals never import `api`
or `db` directly; they receive repositories through an injected context.

## 4. Key mechanisms

### 4.1 Integrations
One `SourceClient` base on `httpx.AsyncClient` provides:
- an async token bucket per source;
- `tenacity` retries on connection errors, 429 and 5xx, with jittered backoff
  and `Retry-After` support;
- a circuit breaker that marks a source degraded for the run;
- a Postgres HTTP cache with a TTL per endpoint class;
- storage of every raw entity payload in `source_records`;
- usage budgets for metered APIs (OpenAlex, LLM).

### 4.2 LLM gateway (provider-independent)

**Business logic never depends on a specific provider or model.** Agents,
services and workflows call one interface:

```python
class LLMGateway(Protocol):
    async def generate_structured(self, task: TaskName, prompt: PromptRef,
                                  inputs: dict, schema: type[T]) -> LLMResult[T]: ...
    async def stream_structured(self, task: TaskName, prompt: PromptRef,
                                inputs: dict, schema: type[T]) -> AsyncIterator[LLMChunk[T]]: ...
    def capabilities(self, task: TaskName) -> LLMCapabilities   # structured output, streaming,
                                                                 # batch, prompt caching, max context
```

- **Task-based model selection:** a configuration file (overridable by env)
  maps each task (`planner`, `relevance_judge`, `relevance_cross_check`,
  `card_writer`, `tutor_answer`, `tutor_lesson`, `tutor_summary`,
  `extractor_abstract`, `extractor_fulltext`, …) to `{provider, model,
  parameters}`. Changing a model is a configuration change plus an
  evaluation run (EVALUATION_FRAMEWORK §4), never a code change.
- **Provider adapters** (first: Anthropic; others can be added) translate
  provider-neutral prompts and Pydantic schemas into each provider's API, and
  map provider errors and stop reasons (refusals, truncation, rate limits)
  to neutral types. Provider SDKs are imported **only** inside
  `llm/adapters/`; a lint rule enforces this.
- **Capability-aware callers:** code asks `capabilities()` instead of
  checking provider names. For example, bulk extraction uses a batch API if
  available and otherwise runs sequentially; prompt caching is used where
  supported.
- **Provisional initial configuration (pending D1):** every task is
  configured to Anthropic `claude-opus-5-5`. It is marked **provisional** in
  the configuration file, in `docs/`, and in run manifests until D1 is
  approved. Cost figures in §7 use it only as an example.
- Validation is provider-independent: schema validation, then semantic
  validation (IDs exist, quotes verify, numbers match evidence), one repair
  attempt, then a recorded error. Refusals and truncation are surfaced as
  errors, never as empty results.
- Prompts are versioned, provider-neutral files. Each output records task,
  provider, model, prompt version and parameters in `llm_usage` and the run
  manifest, so results can be attributed and reproduced.
- A `FakeLLMGateway` serves recorded outputs in tests. A local-model adapter
  is optional for free operation (§8).

### 4.3 Execution modes
| Mode | Used for | Durability | Latency |
|---|---|---|---|
| Batch workflow (LangGraph + Postgres checkpointer) | discovery, assessment Stage A/B, learning setup, full-text analysis, gap investigation, experiment design, proposal, monitoring | survives restarts; human checkpoints via `interrupt()` | minutes |
| On-demand generation (API) | Ask & Learn answers, explanations, recommendation cards, comparison table on request | canonical asks cached by key; conversations persisted | seconds, streamed |

Latest Research scans are **batch** (W8, a parameterised discovery
workflow). Ask & Learn is **on-demand**. Neither needs new infrastructure.

### 4.4 Events
Producers write `domain_events` rows in the same transaction as the change.
A dispatcher in the worker delivers them to consumers (idempotent, with
retries):

| Event | Consumers |
|---|---|
| `paper.added_to_project` | assessment Stage A, field-map staleness, monitor impact check (R5) |
| `document.parsed` / `extraction.completed` | signal recompute, card staleness |
| `objective.updated` | reassessment of all items (Stage A now, Stage B lazily) |
| any change or delete to a graph-projected table (from R2) | Graph Sync Worker: re-project the affected nodes/edges or apply tombstones (§12.6) |
| `override.created` | decision log, feedback pattern detection |
| `gap.updated` / `idea.status_changed` | novelty-dimension recompute, impact watch list |
| `latest_scan.completed` | "new since last visit" counters; (R5) notifications and impact alerts |
| `paper.dates_updated` / `paper.match_decided` | release-type reclassification for affected scan entries |
| `arxiv.announcements_captured` (daily job) | add `preprint_announced` events; upgrade `submission_only` bases; reclassify entries |
| `concept_progress.updated` | learning-path progress, Journey Guide next step |

### 4.5 Journey registry
Nine stages (`discover … propose`), each with a readiness function over
project counts, recommended goals, primary action and pages.
`GET /projects/{id}/journey` returns stage states and one next step.

### 4.6 Verification services
- `QuoteVerifier`: normalised exact match, then a bounded fuzzy match
  (≥ 0.95) that is flagged. Records page and offsets.
- `ClaimValidator`: kind and grounding rules, references, quotes, numbers.
  It also enforces the background-explanation restrictions.
- `CitationValidator` (reports): every factual sentence must cite project
  papers, and cited claims must exist.
- Cross-check runner for high-stakes LLM judgements (RIE §7.2).

### 4.7 Observability
`structlog` JSON logs with run, project, task and source context, and secret
filtering. A per-run event stream for the UI. LLM usage and cost per project
are recorded in `llm_usage`.

### 4.8 Date provenance, release types and time zones

Recent-research correctness depends on dates, and sources disagree about
them. OpenAlex's own documentation warns that publication dates are
unreliable for finding recent records. The `DateResolver` therefore stores
**every date event separately**, per manifestation, with its provenance. It
then derives a first public appearance and a release type, with an
explicit confidence that never overstates what is known.

#### 4.8.1 Manifestations
A **work** (`papers`) can have several **manifestations**
(`paper_manifestations`): an arXiv preprint, a bioRxiv/medRxiv preprint, a
journal or proceedings version, and occasionally others. Identifiers, date
events, documents (PDFs) and evidence spans belong to a manifestation, so
preprint and published versions stay distinct even after they are matched
to one work (§4.8a). Every evidence span therefore says which version its
text came from ("arXiv v2", "journal version").

#### 4.8.2 Date events (kept separately, never merged)

| Event | Meaning | Typical source | Counts as public availability? |
|---|---|---|---|
| `preprint_submitted` | Authors submitted the preprint (arXiv v1 timestamp, UTC). **Not** the moment it became public | arXiv API `published` | ❌. Used only as a labelled fallback (below) |
| `preprint_announced` | The preprint was publicly announced/listed (arXiv daily announcement) | arXiv daily announcement feeds, captured by our daily job (§4.8.5) | ✅ |
| `preprint_posted` | The preprint was posted publicly (bioRxiv/medRxiv posting date; Crossref `posted` for preprints with DOIs) | bioRxiv/medRxiv API, Crossref | ✅ |
| `version_submitted` / `version_announced` / `version_posted` | A revision (v2+) | arXiv, bioRxiv/medRxiv | ✅ for that version only; never the work's first appearance |
| `accepted` | Accepted by a journal (when deposited) | Crossref | ❌ |
| `published_online` | Version of record first available online | Crossref `published-online` | ✅ |
| `issue_published` | Final issue (print/issue) publication | Crossref `published-print`, issue date | ✅ but usually later than online; never earlier evidence of novelty |
| `issued` | Crossref's derived earliest publication date | Crossref `issued` | ✅ (precision checked; recorded as derived) |
| `reported_publication_date` | A secondary source's "publication date" | OpenAlex `publication_date`, Semantic Scholar `publicationDate` | Supporting only (§4.8.3) |
| `index_created` | First appeared in an index | OpenAlex `created_date` (premium filter), our `first_seen` | ❌. "Newly indexed" detection only |
| `metadata_updated` / `metadata_deposited` / `metadata_indexed` | Metadata changed | Crossref `deposited`/`indexed`, OpenAlex `updated_date`, arXiv `updated` | ❌ never |

Every event row records: value (UTC), precision (timestamp/day/month/year),
manifestation, identifier, version, **reporting source**, **upstream
provenance** (§4.8.3), source record, retrieval time, and flags.

#### 4.8.3 Provenance, agreement and independent corroboration

Two sources reporting the same date is **agreement**, not necessarily
**independent corroboration**. OpenAlex and Semantic Scholar both ingest
upstream metadata (e.g. Crossref, arXiv, PubMed, publisher feeds), so their
agreement may simply repeat one upstream value.

- **Reporting source:** the API we read the date from.
- **Upstream provenance:** where that source got the date, recorded only
  when the source exposes it (e.g. a location or source field pointing to
  Crossref or arXiv, an explicit provenance field), with the field path as
  evidence. Otherwise it is `unknown`. It is never guessed.
- **System of record:** the registry or server responsible for that
  manifestation's date: arXiv for arXiv IDs, bioRxiv/medRxiv for their
  preprints, Crossref for DOIs (as deposited by the publisher). A date read
  directly from the system of record is **primary**. It is labelled with its
  meaning ("as deposited by the publisher"), not as absolute truth.

| `date_confidence` | Rule | Default placement |
|---|---|---|
| `verified` | A **primary** public-availability event from the system of record, at day/timestamp precision, with no primary event disagreeing by more than 2 days | Release-type tab |
| `corroborated` | No primary event, but **two claims with established, disjoint upstream provenance** agree within ±1 day | Release-type tab, with "Corroborated by independent sources" and the chain shown |
| `source_agreement` | Several secondary sources agree, but their independence **cannot be established** (unknown or shared upstream) | **Date uncertain**: "Reported by OpenAlex and Semantic Scholar; these may share upstream data" |
| `single_source` | Exactly one secondary claim | **Date uncertain**: "Only OpenAlex reports this date" |
| `conflicting` | Primary events disagree by more than 2 days, or secondary claims disagree with no primary event | **Date uncertain**, all claims shown |
| `uncertain` | Month/year precision only, a future date, or no claim | **Date uncertain** |

`corroborated` will be rare in the MVP, because few sources expose
upstream provenance. That is intended: the system doesn't claim
independence it can't show. Before settling on `source_agreement` or
`single_source`, the resolver looks up the system of record (Crossref by
DOI, arXiv by ID, bioRxiv/medRxiv by DOI). A secondary claim that disagrees
with a primary event is kept and flagged; the primary event stands.

#### 4.8.4 First public appearance and release types

**First public appearance** of a work = the earliest *public-availability*
event across all its manifestations (`preprint_announced`,
`preprint_posted`, `published_online`, `issue_published`, `issued`). It is
labelled with its basis:

- `announced` / `posted` / `published_online` / `issue` — the event itself.
- `submission_only` — for arXiv papers whose announcement date wasn't
  captured. The **v1 submission timestamp** is used as a stand-in and always
  displayed with its meaning: "Submitted to arXiv Nov 8, 21:14 CET — public
  announcement date not verified (usually 1–3 days later)". This basis is
  verified as a *submission* date, never presented as the public release
  date.

The 3-day fetch overlap before the window start is **only a retrieval
tactic**, so that late-announced papers are fetched. It is never evidence
of a release date.

| Release type | Rule |
|---|---|
| New preprint | The work's **first public appearance** is a preprint event in the window (basis announced/posted, or submission_only labelled) with confidence `verified` or `corroborated` |
| New publication | First public appearance is a published-version event in the window, **and** no earlier manifestation is known after a matching search (arXiv, bioRxiv/medRxiv, Crossref relations). Shown with "No earlier preprint found in: …" |
| Published version of an earlier preprint | A published-version event in the window for a work whose first public appearance (a preprint) is **before** the window. **Never presented as new research**: shown under *Updates*, excluded from the "new research" counts and digest, and given no novelty credit (RIE §10.1) |
| Revised version of an older paper | A version event (v2+) in the window, first public appearance before the window |
| Older paper newly indexed | First public appearance before the window, `index_created` in the window (OpenAlex premium capability, or our first-seen date, labelled) |
| Date uncertain | The event that would place the paper in a window tab has confidence `source_agreement`, `single_source`, `conflicting` or `uncertain` |

Rules that always apply:
- Metadata dates never make a paper new.
- Month- or year-precision events never fall inside a window of 31 days or
  less.
- Future dates (beyond retrieval time + 1 day) are flagged as `uncertain`.
- Release types are recomputed when new events or matches arrive
  (`paper.dates_updated`, `paper.match_decided`). A changed type shows
  "Reclassified" and is never silently swapped.

#### 4.8.5 arXiv announcement capture
arXiv's daily announcement (RSS) feeds list each day's new and replaced
papers at announcement time, and keep no history. A small **daily worker
job** reads the feeds for every category mapped in any project. It records
`preprint_announced` / `version_announced` events, with the feed as reporting
source and arXiv as system of record. Papers announced before capture
started, or in unmapped categories, keep `submission_only`. The exact feed
field semantics (which element carries the announcement date and type) must
be verified at implementation and recorded in the integration doc. Until
then, the job only records the announcement day the feed was fetched for.
This needs no new infrastructure: the job runs on the same periodic-task
mechanism as retention.

#### 4.8.6 Time zones (D23)
- **Storage and computation in UTC.** Timestamps are `timestamptz`. Rolling
  windows are `[now_utc − N×24 h, now_utc)`, start inclusive, end exclusive.
- **Date-only events** (Crossref days, bioRxiv/medRxiv dates, arXiv
  announcement days) are calendar dates with `precision = day`. They are
  **never shifted across time zones**. A date-only event *D* is treated as
  the UTC day `[D 00:00, D+1 00:00)`; it is in the window if that day
  overlaps the window, and a day only partly inside is flagged
  `boundary_day`.
- **Display in the user's local zone** (browser zone, overridable). Timestamps
  are converted, date-only values are shown as dates, and window bounds are
  shown in local time. DST is handled by the IANA zone database.

#### 4.8.7 Preprint labelling
- Every **bioRxiv and medRxiv** record is labelled **"Preprint — not
  peer-reviewed"**. arXiv records get the same label, because arXiv
  preprints are moderated but not peer-reviewed.
- The label is removed only when the item being displayed is a separately
  **matched published manifestation** (a Crossref journal-article or
  proceedings record linked by D29 rules). Even then the UI says
  "Journal version (published in <venue>)". It does not assert the details
  of peer review, which Crossref doesn't certify.
- A work with both manifestations shows both, distinctly: "Preprint (arXiv
  v2, not peer-reviewed) · Journal version (2026)". Quotes and evidence say
  which manifestation they come from.

### 4.8a Preprint ↔ publication matching (decision D29)

The `Deduplicator` includes a **Version Matcher** that decides whether two
records are the same work, versions of one work, or different works. It
uses graded evidence and records every decision. **It never merges on title
similarity alone.**

**Evidence features** (each stored in `paper_match_decisions.features`):

| Strength | Feature |
|---|---|
| Decisive | Same DOI; same arXiv ID (any version); an explicit version link from an authoritative source: Crossref `relation` (`is-preprint-of` / `has-preprint`), bioRxiv/medRxiv `/pubs` (preprint DOI → published DOI), or the arXiv `doi` / `journal_ref` field supplied by authors |
| Strong | Both identifiers listed on one Semantic Scholar record (`externalIds`); OpenAlex lists both as locations of one work (strong, not decisive, because OpenAlex sometimes conflates versions) |
| Supporting | Title similarity (normalised token-sort ratio); author similarity (overlap of normalised surname + initials, first-author match); abstract similarity (embeddings); plausible date order and gap (published version after preprint, within ~4 years); consistent venue/type metadata |
| Contradicting | Disjoint author lists; different first author with no identifier link; "Part I/II", "Comment on", "Reply to", "Erratum", "Corrigendum", "Retraction" markers on one side only; thesis vs article type; abstracts clearly different |

**Decision rules** (thresholds versioned and calibrated on G-MATCH):

| Outcome | Rule |
|---|---|
| **Auto-match (same work)** | Any decisive feature with no contradicting feature; **or** strong feature + title ≥ 0.92 + author overlap ≥ 0.6 including the first author; **or**, without any identifier link: title ≥ 0.95 **and** author overlap ≥ 0.8 including the first author **and** abstract similarity ≥ 0.90 **and** plausible date order, with no contradicting feature |
| **Possible match** | Title ≥ 0.90 and author overlap ≥ 0.5, but the auto-match rules aren't met. The records are **linked, not merged**; the UI asks the user to confirm ("Possibly the published version of …") |
| **Related, not same** | Explicit "extended version", erratum, comment or reply relations, or conference ↔ extended journal versions with different DOIs and materially different abstracts. These stay separate papers, linked by relation |
| **No match** | Everything else, including any pair whose only support is title similarity |

**Preservation:**
- A match never deletes or merges **manifestations**. It attaches them to
  one work. Identifiers, documents, evidence spans, `source_records` and
  `paper_dates` stay attached to their own manifestation, so the preprint's
  v1 date and the journal's publication date both survive, distinctly.
- Merges are logged in `paper_merge_events` with the match decision that
  caused them, and can be split again, which restores each record's
  identifiers and date claims by source record.
- User confirmations and rejections are stored as decisions and are never
  overridden by automatic re-matching.

### 4.9 Latest Research scans

A scan is a parameterised run of the discovery workflow (AGENT_DESIGN W8).
There is no separate pipeline.

1. **Plan** queries from the current objective version: the core question,
   each sub-question (subtopic), focus concepts and field-map direction
   labels. Map the objective to arXiv categories and, for life-science
   objectives, to bioRxiv/medRxiv subject categories (Planner proposal, user
   editable; decision **D22**).
2. **Fetch** using date-bounded queries per source:
   - **arXiv:** `cat:<category> AND submittedDate:[start TO end]` category
     sweep (high recall), plus topic queries with the same date range.
   - **bioRxiv / medRxiv** (when the objective is life-science, or the user
     enables them): `/details/{server}/{start}/{end}` for the window, then
     filtered by mapped subject categories and Stage A text match, because
     the API has no full-text search. `/pubs/{server}/{start}/{end}`
     supplies preprint → published links for matching. No official rate
     limit is published, so the client is conservative (1 req/s, cached).
     bioRxiv and medRxiv records carry the "Preprint — not peer-reviewed"
     label (see §4.8.7).
   - **Semantic Scholar:** topic search with a publication-date/year range;
     its dates are secondary.
   - **OpenAlex:** topic search with a publication-date filter; its dates
     are secondary. **Capability-based access (D24):** the client reads
     `OPENALEX_CAPABILITIES` (default: `basic`). Only when `premium_filters`
     is enabled does it use `from_created_date`/`from_updated_date` for
     "newly indexed" detection. Otherwise it falls back to our first-seen
     date. Both paths share one interface and are tested, so paid access can
     be switched on by configuration alone.
   - **Crossref:** `query.bibliographic` with `from-pub-date`/`until-pub-date`
     for journal articles, and DOI lookups to obtain primary (system-of-record) dates
     for candidates from other sources.
3. **Deduplicate and match versions** across sources and against the project
   (`Deduplicator` + Version Matcher, §4.8a).
4. **Resolve dates** and classify release types (§4.8).
5. **Assess** with the RIE: Stage A for all candidates, Stage B for the top-K
   by prescore (default 60) plus any item the user opens. The date window
   filters candidates; it never adds to priority.
6. **Brief the top-K:** build the eight-question **Latest brief** (RIE §10.2):
   the Extractor in abstract mode, Relevance Judge `relation_to_project`, the
   Related Item Linker and the Card Writer. Every statement passes the
   ClaimValidator.
7. **Store** the scan, its entries, briefs, coverage and failures, and emit
   `latest_scan.completed`.

Scans run on demand, and automatically when the page opens if the last scan
is over 24 h old. R5 adds schedules and notifications by consuming the same
event.

### 4.10 Ask & Learn interaction model

Ask & Learn is the conversational front end of the existing Tutor. It is
on-demand, streamed and persisted.

```
User message + view context (item / section / page / selection / card)
      │
      ▼
ContextBuilder ── PROJECT MEMORY (independent of conversations): objective, level,
      │            glossary, saved items, notes, saved explanations, concept progress,
      │            learning path
      │        ── VIEW CONTEXT: what the user is looking at
      │        ── CONVERSATION MEMORY: last 12 turns verbatim + structured summary of
      │            older turns + carried references (re-resolved to original passages)
      ▼
ScopeRouter ──── about_this_paper | about_project | general   (user can override; shown as a chip)
      │
      ▼
EvidenceRetriever ── hybrid search (pgvector + Postgres full-text), scoped:
      │              this paper's sections/equations/extractions → project papers → none;
      │              plus carried references from earlier turns
      ▼
Tutor (LLM) ── answer mode or teaching mode (progressive lesson step);
      │        blocks with claim kinds, evidence handles E1…En only
      ▼
ClaimValidator ── grounded blocks must cite retrieved evidence; quotes verified;
      │           paper equations must match extracted equations; background
      │           blocks may not mention papers/results/numbers not in the project;
      │           summaries and earlier AI answers are not valid evidence
      ▼
Stream to UI → persist tutor_messages (+ evidence links, claims)
             → update concept_progress (teaching mode) → optional save as saved_explanation
```

#### 4.10.1 Conversation memory and evidence preservation (D26)
- The **last 12 turns** go to the model verbatim. Older turns are folded
  into a **structured summary** (`conversation_summaries`) that has two
  parts:
  - `summary_text`: an AI-written recap, `kind = ai_summary`. It is
    context only.
  - `carried_refs`: the IDs of every evidence span, chunk, equation, item
    and saved explanation cited in the summarised turns, plus open questions
    and the concepts covered.
- **The summary is never evidence.** On each turn, the ContextBuilder
  re-resolves `carried_refs` to the original stored passages (quote, page,
  section) and passes those as evidence handles. The validator rejects any
  citation that points to a summary or to a previous assistant message.
- Summarising never deletes messages. Messages are kept until the retention
  policy or the user deletes them. Summaries only control what goes into the
  prompt.
- **Project memory is separate.** Objective, notes, decisions, saved
  explanations, concept progress and the learning path live in project
  tables, are loaded independently, and are unaffected by summarisation or
  conversation deletion.

#### 4.10.2 Retention and deletion
- Per-project policy: **keep until deleted** (default), **delete after N
  days** (30/90/365), or **don't keep history**. With "don't keep history",
  messages exist only for the open session and are purged when it ends.
  Saved explanations and learning progress are still kept.
- **Delete a conversation:** hard-deletes its messages, message-evidence
  links, summaries and the claims that originated only in it. Its teaching
  sessions lose their conversation link, but concept progress and
  understanding-check results remain as project learning progress. Saved
  explanations are independent copies and survive. Canonical cache entries
  (`explanations`) hold no conversation content and are unaffected.
  `llm_usage` rows lose their message references but keep their totals.
- **Delete all conversations** for a project, and separately **reset
  learning progress**. Both actions are explicit and ask for confirmation.
- A daily retention job (worker periodic task) enforces "delete after N
  days" and is idempotent.

#### 4.10.3 Progressive teaching
When the user asks about a concept, or chooses "Teach me", the Tutor builds
a **teaching plan** with these steps, in order:

| Step | Style | Notes |
|---|---|---|
| 1. Intuition | intuitive | |
| 2. Simple example | practical_example | |
| 3. Technical explanation | technical | |
| 4. Mathematical formulation | mathematical | Omitted, with a stated reason, if the concept has no standard formulation. Paper equations only from extracted equations or user selection |
| 5. Algorithmic steps | step_by_step | Pseudocode, labelled "not run" |
| 6. Connection to the current paper | grounded, about_this_paper | Only when a paper is in context, and only from retrieved passages; otherwise "No paper in view" |
| 7. Practical implementation | code | Labelled AI-generated, "not run" |
| 8. Understanding check | check | 1–3 short questions; multiple choice graded deterministically, short answers graded by the Tutor and labelled "AI-graded" |

- The plan is adapted to the level: beginners start at step 1; experts start
  at step 3 by default and can jump anywhere. Steps are generated **lazily**,
  one at a time.
- **User controls at every step:** Next · Simpler · Go deeper / skip to
  advanced · jump to any step · ask a follow-up (interrupts the lesson; a
  "Resume lesson" chip returns to the same step) · stop.
- Non-anchored steps are cached in `explanations` by (concept, level,
  style), so a lesson repeated in another conversation costs nothing.
- **Learning progress is project-level** (`concept_progress`): steps seen,
  highest level reached, check results, and a status (not started, in
  progress, understood (self-reported), check passed, needs review). It
  feeds the learning path and Journey Guide and survives conversation
  deletion.
- Understanding checks are formative and never block the user.

#### 4.10.4 Paper-understanding capability boundaries (MVP)

For each paper in context, the Context Builder computes a **paper access
level** from stored data. The Tutor may only claim what that level supports:

| Access level | Condition | What the tutor can do (R1) | What it must say |
|---|---|---|---|
| `metadata_only` | No abstract available | Concept questions (background, labelled) | "I only have this paper's title and metadata." |
| `abstract_only` | Abstract stored, no processed full text | Abstract-grounded answers, quoting the abstract | Banner "Based on the abstract only". For anything beyond the abstract: "Not available in the extracted text: only the abstract is accessible." |
| `full_text_processed` | A document of this manifestation was retrieved **and** parsed (sections, pages) | Section-grounded answers with page/section citations; lessons with a paper-connection step | Which manifestation the text is from ("arXiv v2"), and "Not found in the extracted text" when retrieval returns nothing |
| `full_text_failed` | Retrieval or parsing failed | Same as `abstract_only` | The failure reason ("PDF could not be parsed") and the upload option |
| `equations_available` | Equations extracted as text: R1 = user-selected text verified against the document's text layer; R2 = arXiv LaTeX source | Step-by-step explanation of that exact equation | Where the equation text came from. If the selection is unreadable (garbled math in the PDF text layer): "I can't read this equation reliably from the PDF text" |

Rules:
- The tutor never claims full-paper understanding when the access level is
  below `full_text_processed`. Phrases such as "the paper shows…" are only
  allowed for content in the accessible text.
- General concept questions are always allowed, labelled as background.
- Equations attributed to a paper are only explained when the access level
  includes `equations_available` for that equation. Otherwise the tutor says
  "This equation is not available in the extracted text" and may explain the
  general concept, labelled as background.
- Multi-paper comparisons use each paper's own access level and say which
  papers were only available as abstracts.

### 4.11 API additions for these features

| Method | Path | Purpose |
|---|---|---|
| GET | `/projects/{id}/latest` | entries for a window: `from`, `to` (default rolling 7 d, UTC), `release_type`, `subtopic`, `method`, `source`, `tier`, `action`, `oa`, `status`; includes coverage, the last scan and the display time zone |
| POST | `/projects/{id}/latest/scans` | start a scan for a window → `202 {run_id, scan_id}` |
| GET | `/latest/scans/{scan_id}` | scan status, coverage, failures, counts by release type |
| GET | `/projects/{id}/latest/digest?scan_id=` | "What's new" digest (grounded, cached per scan and level) |
| GET | `/projects/{id}/latest/{paper_id}/brief` | the eight-question Latest brief |
| PATCH | `/projects/{id}/items/{item_id}` | save, dismiss (+ reason), read later, tags (shared with other pages) |
| GET | `/papers/{id}/dates` | all date events with manifestations, reporting and upstream sources, the derived first public appearance and basis, confidence and release-type history |
| GET | `/papers/{id}/matches` | match decisions (auto, possible, related, rejected) with evidence features |
| POST | `/match-decisions/{id}/confirm` · `/reject` | user confirms or rejects a possible match (merge / keep separate) |
| POST | `/papers/{id}/split` | undo a merge |
| POST | `/tutor/conversations` | `{project_id, anchor?: {item_id, section_id, equation_id, selection}}` |
| GET | `/projects/{id}/tutor/conversations` | list, resume |
| DELETE | `/tutor/conversations/{id}` | delete a conversation (§4.10.2) |
| DELETE | `/projects/{id}/tutor/conversations` | delete all conversations in the project |
| GET / PUT | `/projects/{id}/tutor/retention` | retention policy |
| POST | `/tutor/conversations/{id}/messages` | `{text, level?, style?, intent?, scope?, view_context}` → streamed answer |
| POST | `/tutor/conversations/{id}/lessons` | `{concept or selection, level}` → teaching plan + first step |
| POST | `/lessons/{id}/steps` | `{action: next \| simpler \| deeper \| jump, step?}` → next step (streamed) |
| POST | `/lessons/{id}/checks/{check_id}/answer` | submit an understanding-check answer |
| GET | `/projects/{id}/learning-progress` | concept progress across the project |
| DELETE | `/projects/{id}/learning-progress` | reset learning progress (confirmation required) |
| GET | `/tutor/messages/{id}/sources` | evidence used, with sections, pages and quotes |
| POST | `/tutor/messages/{id}/save` | create a saved explanation (independent copy with claims and evidence) |
| GET / DELETE | `/projects/{id}/saved-explanations` · `/saved-explanations/{id}` | list, view, delete |
| POST | `/tutor/messages/{id}/feedback` | helpful / unclear / wrong |
| POST | `/tutor/messages/{id}/learning-sequence` | build a prerequisite sequence and optionally add it to the learning path |
| GET / PUT | `/me/preferences` | time zone (browser or manual), default level |
| GET | `/projects/{id}/graph` | backend-neutral `GraphView` subgraph: `labels`, `rel_types`, `assertion_policy` (default `established_only`), `include_inferred`, filters. Served by `GraphService` (PostgreSQL in R1, Neo4j from R2), with the same schema either way |
| GET | `/graph/nodes/{uid}/neighbors` | 1-hop neighbours with relationship assertion, confidence and evidence (R1+) |
| GET | `/graph/paths?from=&to=&max_hops=&assertion_policy=` | multi-hop paths, each labelled with its weakest assertion (**R2+**; earlier or in degraded mode: `graph-capability-unavailable`) |
| GET | `/graph/nodes/{uid}/provenance-trail` | proposal/hypothesis → gaps → limitations → papers → evidence (R4) |
| POST | `/relations/{uid}/confirm` · `/reject` | user confirms or rejects an inferred relationship (logged; never automatic) |

## 5. Weaknesses of the previous plan and how this version addresses them

| Weakness in the earlier plan | Risk | Change |
|---|---|---|
| A single relevance score, with "foundational/latest" defined by citations and dates | Violates the new usefulness requirement; misleading rankings | Replaced by the multi-dimension RIE with anti-proxy rules |
| No structured research objective (topic string only) | Relevance can't be judged against sub-questions or constraints | Versioned `research_objectives` with sub-questions, tasks, exclusions and constraints |
| Polymorphic `(subject_type, subject_id)` references | No referential integrity; orphaned notes and feedback | `research_items` supertype with real foreign keys; sections and equations referenced explicitly |
| 14 "agents", many of them deterministic | Over-engineering; hard to test; LLM used where code suffices | Split into deterministic **services** and 10 LLM **agents** (AGENT_DESIGN) |
| Five or more infrastructure services in the MVP (Redis, Qdrant, Neo4j planned) | Ops burden for a single-user tool | MVP runs Postgres + pgvector + GROBID; **Neo4j is sequenced to R2** (not removed) with a graph-ready model from R0; Redis/Qdrant remain optional adapters |
| Generic `entities` table without type-specific attributes | Can't hold licence, size or HF IDs for datasets and models | Typed detail tables (`dataset_details`, `model_details`, `metric_details`) |
| User overrides limited to paper include/exclude | Doesn't meet "override any classification" | Generic `overrides` on any item and field |
| No gold-standard evaluation for relevance | No way to know whether rankings are useful | EVALUATION_FRAMEWORK with gold sets, baselines and release gates |
| 15 planning documents with supersession notes | Hard to follow | Nine canonical documents in `docs/`; `docs/plan/` kept as history |
| OpenAlex treated as free | It now needs a key and is metered | Optional source with a daily budget; the product works without it |

## 6. External dependencies

| Dependency | Purpose | Access | Cost | Main limitations |
|---|---|---|---|---|
| arXiv API | preprint search, metadata, PDFs, LaTeX source; date-range (`submittedDate`) and category queries for Latest Research | no key | free | about 1 request / 3 s, single connection; no citations; metadata quality varies; v1 date is submission time, not announcement time |
| Semantic Scholar Graph API | search, citations, references, recommendations, OA PDF links, citation intents | free API key (apply) | free | introductory 1 req/s with key; shared unauthenticated pool throttles; some abstracts withheld |
| OpenAlex | broad metadata, references, OA locations, field-normalised citation context | API key required since Feb 2026 | free daily allowance, then metered; full-text files charged per file; `from_created_date` / `from_updated_date` filters need a paid plan (not required: enabled later via `OPENALEX_CAPABILITIES`) | search precision; costs at scale; version conflation; publication dates unreliable for recency (OpenAlex's own guidance) |
| Crossref | DOI validation, publisher metadata, authoritative publication dates for DOIs, journal-article date-range search | email (polite pool) | free | rare abstracts; topic search precision is low; dates may be month-only or future-dated |
| Unpaywall | OA PDF locations by DOI | email | free | DOI-only; some links are landing pages |
| bioRxiv / medRxiv API (`api.biorxiv.org`) | life-science preprints by date range (`/details`), preprint → published links (`/pubs`) | no key | free | no full-text search (category + local text filtering); no published rate limit (client uses 1 req/s); medRxiv preprints are not peer-reviewed |
| GROBID | PDF → structured TEI | self-hosted | compute only | weak on tables and formulae; no OCR |
| Hugging Face Hub | models, datasets, paper links | optional token | free | links depend on authors tagging arXiv IDs |
| GitHub REST | repository metadata and search | token | free | 5,000 req/h; search about 30 req/min |
| LLM API (provider-independent gateway; Anthropic adapter first; **provisional**, D1) | planning, judgements, extraction, explanations, critique | API key | metered (§7) | cost; latency; refusals; needs validation |
| Neo4j (R2+) | research knowledge graph (read model) | self-hosted container | compute only (Community Edition, GPLv3); Enterprise features (fine-grained database security, clustering) not required because isolation is enforced in `GraphService` | another stateful service to operate; requires sync, reconciliation and rebuild procedures (§12.6–12.7) |
| Google Scholar | — | — | — | not used (no API; terms forbid scraping) |
| Papers with Code | — | — | — | discontinued in 2025 |

Rate limits and pricing must be re-verified when each integration is built.
Each integration doc records the verification date.

## 7. Operational cost estimates

**Assumptions** (to be replaced by measurements in R1). The model is the
**provisional** initial configuration (D1 not yet approved). These are
Anthropic list prices as of planning (`claude-opus-5-5` $4 / $20 per million input/output tokens;
`claude-sonnet-5-5` $2 / $10; `claude-haiku-5-5` $0.10 / $0.50). A typical
project has 300 candidate papers, 120 included and 50 analysed in full text.
Prompt caching and batch discounts are not counted, so real costs should be
lower.

| Activity | Token estimate | Opus 5.5 (provisional) | If Sonnet 5.5 chosen | If Haiku 5.5 chosen |
|---|---|---|---|---|
| Objective + query planning | ~10k in / 3k out | ~$0.10 | ~$0.05 | <$0.01 |
| Stage B relevance judgements (top 150 papers; ~1.5k in / 0.3k out each) | 225k / 45k | ~$1.80 | ~$0.90 | ~$0.05 |
| Cross-checks (~15% of judgements) | 35k / 7k | ~$0.30 | ~$0.15 | <$0.01 |
| Recommendation cards viewed (~60; 3k / 0.8k each) | 180k / 48k | ~$1.70 | ~$0.85 | ~$0.04 |
| Primer + glossary + learning path | ~60k / 20k | ~$0.65 | ~$0.32 | ~$0.02 |
| Ask & Learn session (~30 turns; ~8k in incl. context and evidence / 0.8k out per turn; before prompt-caching savings) | 240k / 24k | ~$1.45 | ~$0.72 | ~$0.04 |
| Progressive lesson on one concept (8 steps, ~6k in / 0.8k out each; cached steps are free on reuse) | 48k / 6.4k | ~$0.32 | ~$0.16 | <$0.01 |
| **R1 MVP project total (setup + one tutor session)** | | **~$6** | ~$3 | ~$0.15 |
| Latest Research weekly scan (Stage B for 60, abstract extraction for 60, ~20 cards viewed, digest) | ~350k / 85k | ~$3.10 | ~$1.55 | ~$0.08 |
| Full-text extraction, 50 papers (~20k in / 3k out each; batch could halve this) | 1M / 150k | ~$7 | ~$3.50 | ~$0.18 |
| Gap investigation + novelty + red-team (R3) | ~2–3M / 0.4M | ~$16–20 | ~$8–10 | ~$0.40 |
| Proposal drafting (R4) | ~0.3M / 60k | ~$2.40 | ~$1.20 | ~$0.06 |

These are order-of-magnitude figures. Provider and model per task remain
open (decision D1). Any provider with structured output and streaming can be
configured per task through the gateway. Quality must be measured with the evaluation
framework before any downgrade.

**Infrastructure (self-hosted, single user):** one VM or workstation with
4 vCPU, 16 GB RAM and 50–100 GB disk runs everything. GROBID needs about
4 GB RAM; PDFs average 1–3 MB each. Typical cloud cost for such a VM is in
the tens of dollars per month, depending on the provider.

**External data APIs:** free for the MVP volumes, except OpenAlex beyond its
free daily allowance. The OpenAlex client enforces a configurable daily
budget, and the product works with OpenAlex disabled.

## 8. Free-source operation

| Capability | Without any LLM key | With an LLM |
|---|---|---|
| Discovery, dedup, citation expansion, provenance, exports | ✅ full | ✅ + LLM query expansion |
| Research objective | ✅ user fills a form; rule-based sub-questions from keywords | ✅ Planner drafts it |
| RIE Stage A (deterministic signals, tiers, role tags) | ✅ (lower confidence; tiers capped at Recommended without a content judgement) | ✅ + Stage B judgements and cards |
| Recommendation cards | ⚠️ deterministic skeleton only (signals, missing info, extracted statements) | ✅ full |
| Field map | ✅ clusters with keyword labels (c-TF-IDF) | ✅ readable labels |
| Glossary | ⚠️ term list with "appears in" links, no definitions | ✅ definitions by level |
| Full text, sectioning, reading UI | ✅ | ✅ |
| Latest Research: date-verified recent papers, release types, dedup, Stage A tiers, related saved papers (citations/similarity), filters, save/dismiss/notes | ✅ | ✅ + relevance reasons, contributions, overlap checks, digest |
| Ask & Learn: evidence search over the user's papers ("show me where this term appears"); saved explanations and progress views | ⚠️ passages only, no answers or lessons | ✅ full tutor + progressive lessons |
| Version matching (decisive identifier links, bioRxiv `/pubs`, Crossref relations) | ✅ | ✅ |
| Explanations, equations, exercises, extraction, gaps, ideas, proposals | ❌ | ✅ |

A local open-weight model can be plugged into the gateway for zero API cost.
It is not the default, because extraction and judgement quality must pass the
evaluation gates first.

## 9. Scaling path (not needed for the MVP)

| Trigger | Change |
|---|---|
| Multiple workers or users | add Redis-backed rate limiting, or Postgres advisory locks; authentication |
| More than ~5M chunks, or cross-project semantic search at scale | Qdrant adapter for `VectorStore` |
| Very large graphs or heavy analytics | Neo4j Graph Data Science, read replicas, or a dedicated analytics instance (Neo4j itself is part of the planned architecture from R2, §12) |
| Many concurrent long runs | separate worker pools per workflow type |

## 10. Technical limitations (known and accepted)

- Full text only for legally accessible PDFs and user uploads.
- Very recent papers often lack citation data and Semantic Scholar/OpenAlex
  records for several days; Latest Research relies on arXiv, bioRxiv/medRxiv
  and Crossref dates and on content signals for them.
- bioRxiv and medRxiv cover life-science preprints (D22). Other fields with
  little preprint culture (e.g. parts of chemistry, the social sciences and
  the humanities) rely on Crossref and have weaker recall for recent work.
- Publisher dates can be month-precision or revised after the fact. Such
  papers appear as "Date uncertain" rather than in the default view.
- Papers dated only by secondary sources (one source, or several whose
  independence can't be established) go to "Date uncertain" (D28). This
  lowers recall for venues absent from arXiv, bioRxiv/medRxiv and Crossref,
  by design.
- arXiv announcement dates exist only from when the daily capture job
  started, and only for mapped categories. Other arXiv papers are dated by
  their labelled v1 submission time (`submission_only`).
- Upstream provenance is rarely exposed by aggregators, so "corroborated"
  dates will be uncommon.
- Version matching without identifier links is conservative. Some true
  preprint/journal pairs remain "possible matches" until the user confirms
  them.
- Table and formula extraction from PDFs is imperfect. Equations are exact
  only via arXiv LaTeX source.
- Citation intents and contexts are limited to what Semantic Scholar
  provides.
- Index coverage and freshness depend on the external sources.
- LLM judgements are probabilistic. They are mitigated by quotes,
  cross-checks, calibration and user overrides, but not eliminated.
- Compute estimates are only possible when papers report hardware and time.

## 11. Security and hosted deployment

Local development can run without authentication. The API binds to
`localhost` by default, and a startup check refuses a non-local bind unless
`AUTH_MODE` is enabled. **Any hosted deployment, including a private pilot
reachable over a network, is blocked until every requirement below is met
and tested** (IMPLEMENTATION_ROADMAP §8, gate H).

| # | Requirement | Design |
|---|---|---|
| S1 | **Authentication** | OIDC (preferred) or email + password with a modern password hash (argon2id), MFA option; secure, HttpOnly, SameSite session cookies or short-lived tokens; CSRF protection on cookie sessions; account lockout and throttling on login |
| S2 | **Project-level authorization** | Roles per project (owner, editor, viewer). Every API route resolves the project and checks membership in one dependency; repositories require a `ProjectScope`; Postgres row-level security on project-scoped tables as defence in depth; tests for each route (horizontal-access attempts must fail) |
| S3 | **User data isolation** | All user content (projects, notes, overrides, conversations, saved explanations, progress, uploads, assessments) is project-scoped. Shared caches hold only non-user content (public paper metadata, canonical explanations of public papers without project context). Anything containing project context is cached per project. Embeddings of uploaded PDFs are project-scoped. Logs never contain user content beyond IDs. **Graph:** project-scoped nodes and edges carry `scope`, and `GraphService` enforces it on every query; cross-project queries see only the global layer |
| S4 | **Secrets and API keys** | Secrets only from the deployment's secret store or environment, never in the database, repository, logs, prompts or error messages. Separate keys per environment; documented rotation; secret scanning in CI. If users bring their own API keys later, they are encrypted at rest with a managed key and never returned by the API |
| S5 | **Rate limiting and abuse protection** | Per-user and per-IP API rate limits; per-user and per-project LLM and external-API budgets; request and upload size limits; scan and lesson concurrency limits; signup protection; outbound calls only through `SourceClient` with per-source limits, so users can't make us exceed provider terms |
| S6 | **Secure file access** | PDFs and other files live in private storage, never public. They are served only through the API after authorization, or via short-lived signed URLs. Uploads are content-type and size checked and parsed only inside the GROBID container. The downloader fetches only `http(s)` URLs, blocks private/link-local IP ranges and redirects to them (SSRF protection), and enforces size and time limits |
| S7 | **Retention and deletion enforcement** | Deletion and retention (§4.10.2) cascade to messages, summaries, evidence links, project-scoped caches, embeddings, files **and the knowledge graph (tombstones, §12.6)**. The retention job is monitored, and failures alert. Backups follow a documented retention period, after which deleted data is gone. A deletion audit log records what was deleted and when (no content). Account deletion removes all of the user's projects |
| S8 | **Transport and platform** | TLS everywhere; strict CORS; security headers (CSP, HSTS); dependency and container vulnerability scanning in CI; least-privilege database roles; audit log of security-relevant events |

## 12. Research knowledge graph (Neo4j)

Neo4j is a **planned, permanent part of the architecture**. It is the
specialised research knowledge graph that powers graph-native intelligence
from R2 onwards: multi-hop related work, gap and novelty investigation,
provenance trails from proposals back to evidence, and an evolving map of a
field. It is not in the MVP deployment for **sequencing** reasons only. R0–R1
make every entity and relationship graph-ready, so introducing Neo4j in R2
requires no changes to agents, APIs or database models.

### 12.1 Roles of the two stores

| | PostgreSQL | Neo4j |
|---|---|---|
| Role | **Transactional source of truth** for every entity, relationship, evidence link, assertion status and user decision | **Specialised read model** for graph traversal and graph analytics |
| Written by | Application services and workflow nodes (agents never write directly) | **Only** the Graph Sync Worker (§12.6) |
| If lost | Restore from backup | Rebuilt entirely from PostgreSQL (§12.7) |
| Used by | All features | Only through `GraphService` (§12.8) |

### 12.2 Stable identifiers (shared across both databases)

- **Node identity:** every graph node carries `uid` = the PostgreSQL UUIDv7
  primary key of the row it represents. Neo4j enforces a uniqueness
  constraint on `uid` for each label. `research_items.id` already covers
  papers, entities, gaps and ideas. All other node sources (projects,
  objectives, manifestations, authors, research groups, sub-questions,
  directions, limitations, proposals, experiments, results) have UUIDv7 keys
  too.
- **Edge identity:** every relationship carries `uid` = the UUID of its
  PostgreSQL row. Edges that come from link tables with composite keys
  (e.g. `citations`) get a **deterministic UUIDv5** of
  `(relation_type, source_table, from_uid, to_uid, qualifier)`. Re-syncing
  therefore always produces the same edge identity.
- **Versioning:** every synced table has `row_version bigint` (incremented by
  a trigger on update), and each Neo4j node/edge stores the `pg_version` it
  was built from. External identifiers (DOI, arXiv ID, ORCID, ROR/OpenAlex
  institution ID) are properties, never keys.

### 12.3 Node labels

| Label | PostgreSQL source | Scope |
|---|---|---|
| `Project`, `Objective` | `projects`, `research_objectives` | project |
| `Topic` (`kind`: sub_question, direction, task, concept) | `objective_sub_questions`, `research_directions`, `entities` (task, concept) | project (sub-questions, directions) / global (task, concept) |
| `Paper` (work) | `papers` | global |
| `PaperVersion` | `paper_manifestations` | global |
| `Author` | `authors` | global |
| `ResearchGroup` | `research_groups` (institutions/labs) | global |
| `Method` (`kind`: method, algorithm, architecture) | `entities` | global |
| `Dataset`, `Benchmark` | `entities` (+ `dataset_details`) | global |
| `Metric` | `entities` (+ `metric_details`) | global |
| `Limitation` | `limitations` | global (paper-stated) |
| `LimitationCluster` | `limitation_clusters` | project |
| `Gap` | `gaps` | project |
| `Hypothesis` | `ideas` | project |
| `Proposal` | `reports` (type proposal), `experiment_plans` | project |
| `Experiment` | `experiments` | project |
| `Result` (`kind`: paper_reported, user_reported) | `reported_results`, `experiment_results` | global (paper-reported) / project (user-reported) |
| `Repository`, `Model` (R4) | `code_repositories`, `entities` (+ `model_details`) | global |

### 12.4 Relationship types and their single source of truth

Relationships fall into two classes:

- **Research relationships** make a claim about the research world, such
  as "A cites B" or "P introduces method M". They always carry an
  assertion, provenance and the evidence required for that assertion
  (§12.5).
- **Structural relationships** only express how ResearchPilot's own records
  are organised, such as "this version belongs to this work" or "this gap
  belongs to this project". Their assertion is `structural`. They carry no
  research claim, need no evidence, and are never shown or counted as
  findings. They can't be "rejected": a wrong structure is corrected by
  fixing the record.

**Every relationship type has exactly one PostgreSQL source.** A test
(R1-65) fails if the relation registry maps a type to more than one source,
or if any other table stores the same kind of link.

| Type | Class | Endpoints | Single PostgreSQL source | Typical assertions |
|---|---|---|---|---|
| `CITES` | research | Paper → Paper | `citations` | `source_metadata` |
| `AUTHORED_BY` | research | Paper → Author | `paper_authors` | `source_metadata` |
| `AFFILIATED_WITH` | research | Author → ResearchGroup (property: paper uid, period) | `author_affiliations` | `source_metadata` |
| `INTRODUCES` | research | Paper → Method/Dataset/Benchmark/Metric | `entity_links` (role `introduces`) | `author_reported`, `extracted` |
| `USES_METHOD` | research | Paper/Proposal/Experiment → Method | `entity_links` (role `uses_method`) | `extracted`, `user_asserted` |
| `EVALUATES_ON` | research | Paper/Method/Proposal/Experiment → Dataset/Benchmark | `entity_links` (role `evaluates_on`) | `extracted`, `author_reported`, `user_asserted` |
| `REPORTS_LIMITATION` | research | Paper → Limitation | `limitations` (one row = the Limitation node and its edge) | `author_reported`, `extracted`, `inferred` |
| `EXTENDS` | research | Paper → Paper, Method → Method (property `subtype`: improves_on, extends) | `research_relations` | `author_reported`, `extracted`, `inferred` |
| `CONTRADICTS` | research | Paper ↔ Paper, Result ↔ Result, Paper → Hypothesis/Paper in project (challenges) | `research_relations` | `computed` (result conflicts), `extracted`, `inferred` |
| `RELATED_TO` | research | any → any (property `basis`: similarity, co_citation, direction_membership, overlap, alternative, reproduces, compares_with, topic) | `research_relations` | `computed`, `inferred` |
| `ADDRESSES` | research | Paper → Gap/Topic, Proposal → Hypothesis, Experiment → Hypothesis | `research_relations` | `inferred`, `user_asserted`, `user_confirmed` |
| `DERIVED_FROM` | research | Gap → Limitation/Paper, Hypothesis → Gap, Proposal → Hypothesis | `research_relations` | `computed`, `hypothesized`, `user_asserted` |
| `VALIDATED_BY` | research | Hypothesis → Result/Experiment (property `outcome`) | `research_relations` | `user_asserted`, `computed` |
| `IMPLEMENTED_BY` (R4 registry extension) | research | Paper/Method/Model → Repository (properties: link_source, is_official) | `item_code_links` | `extracted` (URL in paper text), `source_metadata` (HF paper page), `inferred` (name search: "possible") |
| `HAS_VERSION` | structural | Paper → PaperVersion | `paper_manifestations.paper_id` | `structural` |
| `PART_OF` | structural | Objective → Project; Topic → Objective/Topic; Gap/Hypothesis/Proposal/Experiment → Project; Result(user) → Experiment; Experiment → Proposal; Limitation → LimitationCluster | the child row's foreign key (one FK per label pair, listed in the registry) | `structural` |
| `IN_PROJECT` | structural | Paper → Project (properties: inclusion, reading status) | `project_items` | `structural` |
| `RESULT_FOR` | structural | Result → Method/Dataset/Metric (property `role`) | the result row's FK columns (`reported_results`, `experiment_results`) | `structural` (the claim and its evidence belong to the Result node) |

Consequences of the single-source rule:
- `entity_links` replaces `paper_entity_mentions`, with a generic subject
  (paper, method, proposal, experiment). Roles that have no graph type
  (`compares_against`, `reports_metric`) stay in `entity_links` for RIE use
  and are not projected.
- `paper_relations` and `direction_members` are folded into
  `research_relations` (EXTENDS/CONTRADICTS/RELATED_TO with properties).
  Hypothesis → gap, proposal → hypothesis and experiment → hypothesis links
  live only in `research_relations`, not as foreign-key columns.
- **Snapshots are never graph sources.** Latest Research entries, briefs,
  cards, reports and conversation content may reference relationship
  `uid`s, but they never store links of their own.
- `paper_contributions` is node data (a contribution summary on the Paper),
  not a relationship source.

New relationship types are added through the **relation registry** (§12.6),
which must keep the single-source rule.

### 12.5 Provenance, confidence and evidence

Every **research** relationship, in PostgreSQL and in Neo4j, carries:

| Property | Meaning |
|---|---|
| `assertion` | `source_metadata` (reported by an external index, e.g. citations, authorship) · `author_reported` (stated in the paper; quote-verified) · `extracted` (extracted by ResearchPilot from text; evidence verified) · `computed` (deterministic statistic, e.g. co-citation, result conflict) · `inferred` (model judgement, not proven by a quote) · `hypothesized` (AI-generated hypothesis link) · `user_asserted` · `user_confirmed` · `rejected`. Structural relationships use `structural` (§12.4) |
| `confidence` | 0–1 where meaningful (null for `source_metadata`, `structural` and user assertions) |
| `evidence` | evidence span IDs (with manifestation), source record IDs, signal IDs |
| `provenance` | producing service/agent and version, prompt version, task/provider/model (if any), source API, created and updated time, `pg_table`, `pg_id`, `pg_version` |
| `scope` | `global` or a `project_id` |
| `status` | `active` · `retracted` (source withdrew it or it was superseded) |

**Evidence is required by assertion** (database constraint plus the single
write path below):

| Assertion | Required |
|---|---|
| `source_metadata` | `source_record_id` of the API response that reported it |
| `author_reported` | ≥ 1 evidence span with `verification ∈ (exact, fuzzy)` |
| `extracted` | ≥ 1 verified evidence span |
| `computed` | signal or computation reference (inputs and method version); no quote needed |
| `inferred` | confidence + at least one evidence reference (span or signal) supporting the judgement + producing task/model |
| `hypothesized` | the gap/evidence it was derived from + producing task/model |
| `user_asserted` / `user_confirmed` | acting user and time; evidence optional |
| `rejected` | acting user (or verification job) and reason |
| `structural` | none |

**Inferred is never treated as established:**
- `inferred` and `hypothesized` relationships are excluded from traversals
  by default. Every `GraphService` query takes an explicit `AssertionPolicy`
  (default `established_only`: source_metadata, author_reported, extracted,
  computed, user_asserted, user_confirmed, structural). Including inferred
  edges requires `include_inferred = true`, and every path then reports its
  weakest assertion.
- Results derived from paths that contain inferred edges are labelled
  `ai_interpretation` or `unverified_hypothesis`, never `reported_finding`.
- An inferred relationship is promoted only by verification (a verified
  quote turns it into `extracted`) or by a user (`user_confirmed`). Both are
  logged. Nothing is promoted by repetition or by agreement between models.

**Rejected relationships cannot silently reappear:**
- **One write path.** All relationship writes go through the
  `RelationWriter` service, including writes by extractors, judges,
  matchers, sync of source metadata, and users. No other code inserts into
  relationship tables (enforced by repository design and a lint rule).
- **Natural keys.** Each relationship table has a unique natural key (e.g.
  `research_relations(type, from_uid, to_uid, qualifier, scope)`,
  `entity_links(subject_uid, entity_id, role, scope)`). A re-extraction
  therefore finds the existing rejected row instead of creating a new one.
- **Rejection is sticky.** A trigger blocks any change *from* `rejected`
  unless it is made by a user action. `RelationWriter` turns an automatic
  write that hits a rejected row into a no-op and logs it as "suppressed".
- **Fuzzy duplicates.** For relationships without a stable natural key
  (e.g. limitations whose wording varies, similarity links), rejection
  writes a `relation_suppressions` fingerprint (type, endpoints, and a hash
  of the evidence span or normalised text). `RelationWriter` refuses new
  rows matching it.
- **Sync and rebuild.** Rejected rows are ineligible for projection, so
  they are removed from Neo4j and never re-created by resync, reconciliation
  or a full rebuild.

### 12.6 Synchronisation (asynchronous, idempotent)

```
PostgreSQL write ─(same transaction)─▶ domain_events (outbox; includes deletes as tombstones)
                                            │
                                   Graph Sync Worker (worker periodic + event-driven)
                                            │ for each event: load CURRENT state of the
                                            │ affected rows from PostgreSQL (state-based, not payload-based)
                                            ▼
                                   Graph Projector + relation registry
                                   (PG row → GraphNode / GraphEdge with uid, pg_version,
                                    assertion, evidence, scope)
                                            │
                                            ▼
                                   Neo4j: MERGE on uid; apply only if pg_version ≥ stored version;
                                          missing endpoints MERGEd as stubs and completed later
                                            │
                                   graph_sync_state (per uid: synced_version, status, attempts, error)
```

- **Idempotent:** MERGE by `uid` plus a version guard means replaying any
  event, in any order, gives the same graph.
- **Sync eligibility (validated records only):** a row is projected only if
  it passes the eligibility rule for its type. Extractions need verified
  evidence. Matches must not be `possible_match`. Claims hidden pending
  review are excluded. `rejected` relationships are excluded. From R2 the
  established assertions are synced; `inferred` and `hypothesized`
  relationships are synced from R3, always labelled.
- **Retries:** exponential backoff. After N attempts the item goes to
  `graph_dead_letters`, an alert is raised, and reconciliation retries it
  later. Neo4j being unavailable never blocks PostgreSQL writes.
- **Deletion propagation:** deletes (user deletions, retention expiry,
  project and account deletion, merge splits) and rejections emit tombstone
  events with the `uid`s. The worker removes the nodes (`DETACH DELETE`) or
  edges. Deletion markers (§12.6a) make deletions survive worker downtime.
  Retention enforcement (S7, gate H) includes the graph.
- **Merges and splits:** when versions are matched (D29), the `PaperVersion`
  nodes stay distinct and are connected to the surviving `Paper`. A split
  re-projects both works from PostgreSQL.

### 12.6a Deletion markers (`entity_tombstones`)

Deletion markers exist only so that deletions reach the graph reliably, even
while Neo4j is down or before it exists (R1). They are not an archive.

- **Minimum metadata only:** `uid` (an opaque UUID, or for composite links
  the one-way UUIDv5 hash; neither reveals content), `kind` (node label or
  relationship type), `reason` (user_delete, retention, project_delete,
  account_delete, merge_split, retracted, rejected), `deleted_at`,
  `graph_removed_at`, `verified_absent_at`, `attempts`, `purge_after`.
  **No** titles, text, names, emails, notes, conversation content, endpoint
  IDs, project IDs or user IDs.
- **Retention period:** a marker is purged when it has been verified absent
  from Neo4j by a reconciliation run, and in any case **30 days** after
  `deleted_at` (hard cap). If a marker reaches the cap unverified, an alert
  is raised before purging. The reconciliation orphan sweep, which deletes
  every graph element whose `uid` has no eligible PostgreSQL row, still
  guarantees removal afterwards.
- **Use in reconciliation:** reconciliation first applies pending markers,
  then confirms absence (`verified_absent_at`), then runs the orphan sweep.
  Markers make deletion fast and auditable; the orphan sweep makes it
  complete.
- **Use in rebuilds:** a full rebuild projects only rows that currently
  exist and are eligible in PostgreSQL, so deleted data can't come back.
  Pending markers are applied to the new database before the switch-over,
  covering deletions made during the rebuild.
- **Compliance with deletion and retention policies:**
  - Conversation deletion and retention expiry write markers for affected
    project-scoped graph elements (e.g. inferred relationships created in
    that conversation, if any).
  - Project deletion writes markers for every project-scoped node and edge.
  - Account deletion writes markers for all of the user's projects.
  - Global knowledge (public papers, authors) is not deleted when a user
    leaves, because it isn't personal content.
  - The marker never keeps the deleted content. After purge, only the
    aggregate `deletion_log` remains (counts by scope, timestamps, and a
    one-way hash instead of user/project IDs).
- **Backups:** PostgreSQL backups follow the S7 retention period. Markers
  are not used to re-apply deletions after a backup restore; that is
  covered by the documented restore procedure (S7). Neo4j has no backups of
  its own: it is rebuilt.

### 12.7 Reconciliation and rebuild
- **Scheduled reconciliation** (daily, plus on demand) compares PostgreSQL
  and Neo4j per label and per relationship type: counts, then hashes of
  `(uid, pg_version)` in batches. Mismatched batches are re-projected, and
  orphans that are no longer in PostgreSQL are deleted. Results are logged in
  `graph_sync_runs`.
- **Full rebuild:** a command that recreates the graph from PostgreSQL into
  a fresh database and switches the service over when it completes, using a
  blue/green database name. The Neo4j *data* can therefore always be
  discarded and regenerated. The Neo4j *service* is required from R2.
- Every sync batch increments a `graph_version` stored in Neo4j. Results that
  depend on the graph (R3 signals) record the `graph_version` and query
  template used, for reproducibility.

### 12.8 `GraphService`: the only way to use the graph

```python
class GraphService(Protocol):
    async def neighbors(self, uid, rel_types, direction, policy: AssertionPolicy,
                        scope: ProjectScope, limit) -> GraphView: ...
    async def paths(self, from_uid, to_uid, rel_types, max_hops, policy, scope) -> list[GraphPath]: ...
    async def subgraph(self, scope, labels, rel_types, policy, filters) -> GraphView: ...
    async def related_work(self, paper_uid, policy, scope, limit) -> list[RankedNode]: ...
    async def pattern_counts(self, pattern: NamedPattern, params, policy, scope) -> list[PatternRow]: ...
    async def provenance_trail(self, uid, scope) -> GraphView: ...   # proposal → … → evidence
```

- **Two implementations behind one interface:**
  - `PostgresGraphService` (R0–R1, and as a fallback): recursive CTEs plus
    in-memory `networkx` for small project graphs.
  - `Neo4jGraphService` (R2+): parameterised Cypher templates (and optionally
    the Graph Data Science library for analytics).
  - A configuration flag selects the backend (PostgreSQL in R0–R1; Neo4j
    from R2, with PostgreSQL only as the degraded fallback). A **parity test
    suite** runs the R1 capability set against both.
- **No direct Neo4j dependency:** only `graph/adapters/neo4j/` imports the
  Neo4j driver (lint rule). Agents, services and API routers use
  `GraphService`. API responses use a backend-neutral `GraphView` schema
  (nodes and edges with assertion, confidence, evidence), so switching
  backends changes no API.
- **Named patterns only:** queries are predefined, parameterised templates
  (e.g. `methods_on_dataset`, `limitation_along_extends_chain`,
  `contradiction_paths`). No user- or LLM-composed Cypher is executed.
- **Scope enforcement:** every call takes a `ProjectScope`. Global nodes are
  visible to all; project-scoped nodes and edges only to members of that
  project. This holds even though Neo4j Community Edition has no per-user
  database security, because isolation is enforced in the service (gate H,
  H3). Cross-project queries see only the global layer.
**Capabilities by release and backend.** The API contract (`GraphView`
nodes/edges with assertion, confidence and evidence; named patterns;
assertion policy; scope) is the same for both backends. The PostgreSQL
implementation is **not** required to reproduce every Neo4j capability.

| Capability | R1 (PostgreSQL `GraphService`) | R2 (Neo4j, required) | R3 (Neo4j) |
|---|---|---|---|
| Citation graph of a project (papers and `CITES` among them, plus 1-hop external references/citations) | ✅ | ✅ | ✅ |
| Paper versions (`HAS_VERSION`) and work ↔ version navigation | ✅ | ✅ | ✅ |
| Direct neighbours (1 hop) of any node, filtered by type and assertion policy | ✅ | ✅ | ✅ |
| Basic related-paper exploration (co-citation, bibliographic coupling, similarity, direction membership: computed `RELATED_TO`) | ✅ | ✅ | ✅ |
| General multi-hop traversal and path finding (`paths`, up to N hops, mixed types) | ❌ (returns `capability_unavailable`) | ✅ | ✅ |
| Rich knowledge-graph exploration (multi-label subgraphs, method/dataset/metric neighbourhoods, `EXTENDS` evolution chains) | ❌ | ✅ | ✅ |
| Graph-assisted gap discovery (named patterns: structural holes, limitation propagation) | ❌ | ❌ | ✅ |
| Contradiction analysis (`CONTRADICTS` paths, conflicting results neighbourhoods) | ❌ | ❌ | ✅ |
| Novelty investigation (hypothesis neighbourhood before external search) | ❌ | ❌ | ✅ |
| Provenance trails (R4), evolving-graph history and impact traversal (R5) | ❌ | ❌ | ❌ (R4/R5) |

- `GraphService.capabilities()` reports what the active backend supports.
  Unsupported calls return a typed `capability_unavailable` result, and the
  API returns RFC 7807 `graph-capability-unavailable` with the release in
  which it becomes available. Callers never fake a capability.
- The **parity suite** (R2-15) covers the R1 capability set only.
- From R2, **Neo4j is a required service**. A deployment without it is in a
  *degraded* state: the health endpoint reports `graph: degraded`, only the
  R1 capabilities remain (served by the PostgreSQL implementation), and
  graph-only features show "Graph analysis temporarily unavailable". It is
  not a supported configuration. The backend switch exists for R0–R1,
  tests and degraded operation, not as a way to run without Neo4j.

### 12.9 How graph intelligence grows by release

| Release | Graph capability |
|---|---|
| R0–R1 | Graph-compatible model: stable UUIDs, `row_version`, assertion/confidence/evidence/provenance on every relationship table, `research_relations`, relation registry, tombstones, `GraphService` with the PostgreSQL implementation (citation graph, field map, related items). **No Neo4j deployment required** |
| R2 | **Neo4j deployed as a required service** (`neo4j` container), projector + sync worker + reconciliation + rebuild; synchronises **validated** records (established assertions); parity tests; the citation graph, field map and evolution views move to `Neo4jGraphService` where they benefit |
| R3 | Graph traversal for **gap discovery** (e.g. method × dataset structural holes, limitations propagated along `EXTENDS` chains, under-connected communities), **related-work analysis** (multi-hop `CITES`/`EXTENDS`/`USES_METHOD` with assertion policies), and **novelty investigation** (the neighbourhood of a hypothesis's methods, datasets and limitations, and contradiction paths) before and alongside external searches. Inferred and hypothesised relationships are synced, labelled |
| R4 | `Proposal`, `Experiment` and `Result` connected through `DERIVED_FROM`, `ADDRESSES`, `VALIDATED_BY`, `USES_METHOD` and `EVALUATES_ON`; **provenance trails** from a proposal back to gaps, limitations, papers and quoted evidence; repository and model nodes |
| R5 | **Continuously evolving graph:** monitors add nodes and edges incrementally; temporal properties (`first_seen`, `valid_from`, `retracted_at`) and `graph_version` history; impact alerts computed by traversal (new paper → `ADDRESSES`/`CONTRADICTS` → accepted hypothesis); cross-project discovery on the global layer only |
