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
| A9 | **Swappable infrastructure behind interfaces** | `JobQueue`, `VectorStore`, `GraphStore`, `LLMGateway`, `ObjectStore` |

## 2. Runtime topology (MVP)

```
Browser ──▶ frontend (React SPA via nginx)
               │  /api/v1  REST + SSE (+ streamed explanation responses)
               ▼
            api (FastAPI)
              ├─ routers / auth (later)
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

**Five containers:** `postgres` (with pgvector), `grobid`, `api`, `worker`,
`frontend`. Redis, Qdrant and Neo4j are not needed for the MVP; adapters can
be added behind the interfaces in A9 if scale requires them (see §9).

## 3. Backend modules

```
researchpilot/
  core/          settings, logging, errors, ids, clock, budgets
  domain/        Pydantic models: items, papers, identifiers, evidence, claims,
                 objective, assessment, card, journey
  db/            SQLAlchemy models, Alembic migrations, repositories
  integrations/  base SourceClient (rate limit, retry, cache, circuit breaker,
                 provenance) + arxiv, semantic_scholar, openalex, crossref,
                 unpaywall, huggingface, github
  processing/    pdf resolver, downloader, grobid client, arXiv LaTeX source,
                 sectioning, chunking, embeddings
  intelligence/  ← Research Intelligence Engine
                 signals/ (plugins per item type and dimension)
                 scoring.py, tiers.py, profiles.py, overrides.py,
                 feedback.py, cards.py, staleness.py
  services/      dedup, enrichment, field_map, glossary, learning_path,
                 comparison tables, conflict detection, report builder,
                 quote_verifier, claim_validator, citation_validator,
                 dates/ (date resolver, release-type classifier),
                 latest/ (scan planner, related-paper linker, digest assembly),
                 retrieval/ (evidence retriever: hybrid pgvector + full-text),
                 tutor/ (context builder, scope router, conversation memory)
  llm/           LLMGateway, Anthropic implementation, fake gateway,
                 prompt registry (versioned files)
  agents/        LLM-backed agents (see AGENT_DESIGN)
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

### 4.2 LLM gateway
- `generate_structured(task, prompt_ref, inputs, schema, level=None)` returns
  a validated Pydantic object plus usage metadata.
- The default implementation uses the Anthropic SDK structured outputs with
  `claude-opus-5-5`, overridable per task through environment variables.
  `refusal` and `max_tokens` stop reasons are surfaced as errors, never as
  empty results.
- Semantic validation runs after schema validation: IDs must exist, quotes
  must verify, numbers must match the evidence. One repair attempt is made,
  then the error is recorded.
- Bulk extraction can use the Message Batches API. Stable system prompts use
  prompt caching.
- A `FakeLLMGateway` serves recorded outputs in tests. A local-model adapter
  is optional for free operation (lower quality; see §8).

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
| `override.created` | decision log, feedback pattern detection |
| `gap.updated` / `idea.status_changed` | novelty-dimension recompute, impact watch list |
| `latest_scan.completed` | "new since last visit" counters; (R5) notifications and impact alerts |
| `paper.dates_updated` | release-type reclassification for affected scan entries |

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

### 4.8 Date provenance and release-type classification

Recent-research correctness depends on dates, and sources disagree about
them. OpenAlex's own documentation warns that publication dates are
unreliable for finding recent records. The `DateResolver` service therefore
stores **every date claim separately**, then derives a first public date and
a release type with explicit confidence.

**1. Collect date claims** (`paper_dates`, one row per claim) with: date type,
value, precision (day/month/year), source, source record, and retrieval time.

| Source | Field | Stored as date type | Used as publication date? |
|---|---|---|---|
| arXiv | `published` (v1 submission timestamp) | `preprint_v1_submitted` | ✅ first public preprint date |
| arXiv | per-version submission dates (from the abstract page/OAI metadata) | `version_submitted` (with version number) | ✅ for that version only |
| arXiv | `updated` | `latest_version_submitted` | ❌ (version event, not first release) |
| Crossref | `published-online`, `published-print`, `issued` | `published_online`, `published_print`, `issued` | ✅ (precision checked) |
| Crossref | `created`, `deposited`, `indexed` | `metadata_created`, `metadata_deposited`, `metadata_indexed` | ❌ never |
| OpenAlex | `publication_date` | `openalex_publication_date` | ⚠️ supporting only |
| OpenAlex | `created_date` | `index_created` | ❌ (used only to detect "newly indexed") |
| OpenAlex | `updated_date` | `metadata_updated` | ❌ never |
| Semantic Scholar | `publicationDate` | `s2_publication_date` | ⚠️ supporting only (often missing or year-only) |
| ResearchPilot | first time we saw the paper | `first_seen_by_researchpilot` | ❌ (fallback for "newly indexed" detection) |

**2. Derive** `first_public_date` = the earliest **authoritative** claim
(arXiv v1, or Crossref online/print/issued) at day precision.
`date_confidence` is:
- `verified` — authoritative claim at day precision, and no conflicting
  authoritative claim;
- `single_source` — only a supporting claim (OpenAlex/S2) at day precision;
- `conflicting` — authoritative claims disagree by more than 2 days;
- `uncertain` — only month/year precision, or no claim at all.

**3. Classify the release type** relative to the scan window
`[start, end)`:

| Release type | Rule |
|---|---|
| New preprint | arXiv v1 submitted in window |
| New publication | Crossref online/print/issued in window **and** no earlier version known |
| Published version of an earlier preprint | Crossref date in window **and** an earlier linked preprint exists (shown with the preprint date) |
| Revised version of an older paper | a new version submitted in window **and** first public date before the window |
| Older paper newly indexed | first public date before the window **and** first indexed (OpenAlex `created_date`, where available, or our first-seen date) in window |
| Date uncertain | candidate found in window, but confidence is `uncertain` or `conflicting` on the date that would place it there |

Rules that always apply:
- A metadata-change date never makes a paper "new".
- Month- or year-precision dates never fall "inside" a 7-day window. Such
  papers go to Date uncertain.
- Future dates (beyond the retrieval time plus 1 day) are flagged and treated
  as uncertain.
- A paper whose only day-precision date comes from a supporting source
  (OpenAlex or Semantic Scholar; confidence `single_source`) may appear in
  *New research*, but with a visible "Date from one secondary source" badge.
  If it has a DOI, a Crossref lookup is attempted first, and Crossref's date
  takes precedence when present.
- Release type is recomputed when new date claims arrive
  (`paper.dates_updated`). A changed type is shown, never silently swapped.

**Known caveat:** arXiv's v1 timestamp is the submission time. Public
announcement can lag by one to a few days (weekends and holidays). The page
labels the date "v1 submitted", and scans overlap the window start by 3 days
so papers announced late aren't missed. Inclusion is still decided by the
submission date.

### 4.9 Latest Research scans

A scan is a parameterised run of the discovery workflow (AGENT_DESIGN W8),
with no new pipeline.

1. **Plan** queries from the current objective version: the core question,
   each sub-question (subtopic), focus concepts and field-map direction
   labels. Map the objective to arXiv categories (Planner proposal, user
   editable).
2. **Fetch** using date-bounded queries per source:
   - arXiv: `cat:<category> AND submittedDate:[start TO end]` category sweep
     (high recall), plus topic queries with the same date range;
   - Semantic Scholar: topic search with a publication-date range (supporting
     dates only);
   - OpenAlex (if enabled): topic search with a publication-date filter. The
     `from_created_date` filter used for "newly indexed" detection needs a
     paid OpenAlex plan, so it is used only when available, and otherwise our
     own first-seen date is the fallback;
   - Crossref: `query.bibliographic` with `from-pub-date`/`until-pub-date`
     for journal articles, plus DOI lookups to confirm publication dates for
     candidates from other sources.
3. **Deduplicate** across sources and against the project (same
   `Deduplicator`).
4. **Resolve dates** and classify release types (§4.8).
5. **Assess** with the RIE: Stage A for all candidates, Stage B for the top-K
   by prescore (default 60) plus opened items. The objective profile is the
   project's own; the recency window is a filter, not a score.
6. **Enrich the top-K:** abstract-level contribution/method/dataset
   extraction (Extractor, abstract mode, with quotes verified against the
   abstract); related saved papers (citations where known; otherwise
   similarity, labelled); overlap/challenge check against the project's
   direction.
7. **Store** the scan, its entries, coverage and failures, and emit
   `latest_scan.completed`.

Scans run on demand, and automatically when the page opens if the last scan
is over 24 h old. R5 adds schedules and notifications by consuming the same
event.

### 4.10 Ask & Learn interaction model

Ask & Learn is the conversational front end of the existing Tutor. It is
on-demand, streamed and persisted.

```
User question + view context (item / section / page / selection / card)
      │
      ▼
ContextBuilder ── project context: objective, level, glossary, saved items, notes (short)
      │        ── view context: what the user is looking at
      │        ── conversation memory: last 12 turns verbatim + rolling summary of older turns
      ▼
ScopeRouter ──── about_this_paper | about_project | general   (user can override; shown as a chip)
      │
      ▼
EvidenceRetriever ── hybrid search (pgvector + Postgres full-text), scoped:
      │              this paper's sections/equations/extractions → project papers → none
      ▼
Tutor (LLM) ── structured answer: blocks with claim kinds, evidence handles E1…En,
      │        style, level, missing prerequisites, "not found in sources" flags
      ▼
ClaimValidator ── grounded blocks must cite retrieved evidence; quotes verified;
      │           paper equations must match extracted equations; background
      │           blocks may not mention papers/results/numbers not in the project
      ▼
Stream to UI → persist tutor_messages (+ claims) → optional save as note
```

- **Grounding order:** for a question about the current paper, the answer
  first states what the paper says, with sources, then background if useful,
  labelled as such. If retrieval finds nothing, the answer says so and offers
  background.
- **Caching:** "canonical asks" (an explain action on a fixed subject with a
  given level and style, and no prior turns) are served from or written to
  the `explanations` cache. Follow-ups are conversation-specific and not
  shared-cached. Prompt caching covers the stable prefix (system prompt +
  project context).
- **Equations:** taken from `equations` (arXiv LaTeX) or a user selection.
  When a paper's equation isn't available, the tutor says so and may explain
  the general concept, labelled as background.
- **Prerequisites:** the Tutor returns missing prerequisite concepts. These
  are matched to glossary/concept items, and "Build a learning sequence"
  calls the existing Curriculum Builder.
- **Saving:** "Save to project" creates a `notes` row linked to the message
  and, where relevant, the item. Claims and sources are kept.
- **Conversation context** is project-scoped. It never crosses projects, and
  conversations can be deleted.

### 4.11 API additions for these features

| Method | Path | Purpose |
|---|---|---|
| GET | `/projects/{id}/latest` | entries for a window: `from`, `to` (default rolling 7 d), `release_type`, `subtopic`, `method`, `source`, `tier`, `oa`, `status`; includes coverage and the last scan |
| POST | `/projects/{id}/latest/scans` | start a scan for a window → `202 {run_id, scan_id}` |
| GET | `/latest/scans/{scan_id}` | scan status, coverage, failures, counts by release type |
| GET | `/projects/{id}/latest/digest?scan_id=` | "What's new" digest (grounded, cached per scan and level) |
| PATCH | `/projects/{id}/items/{item_id}` | save, dismiss (+ reason), read later, tags (shared with other pages) |
| GET | `/papers/{id}/dates` | all date claims with sources, the derived first public date, confidence and release-type history |
| POST | `/tutor/conversations` | `{project_id, anchor?: {item_id, section_id, equation_id, selection}}` |
| GET | `/projects/{id}/tutor/conversations` | list, resume |
| DELETE | `/tutor/conversations/{id}` | delete a conversation |
| POST | `/tutor/conversations/{id}/messages` | `{text, level?, style?, intent?, scope?, view_context}` → streamed answer |
| GET | `/tutor/messages/{id}/sources` | evidence used, with sections, pages and quotes |
| POST | `/tutor/messages/{id}/save` | save as a note (optionally linked to an item) |
| POST | `/tutor/messages/{id}/feedback` | helpful / unclear / wrong |
| POST | `/tutor/messages/{id}/learning-sequence` | build a prerequisite sequence and optionally add it to the learning path |

## 5. Weaknesses of the previous plan and how this version addresses them

| Weakness in the earlier plan | Risk | Change |
|---|---|---|
| A single relevance score, with "foundational/latest" defined by citations and dates | Violates the new usefulness requirement; misleading rankings | Replaced by the multi-dimension RIE with anti-proxy rules |
| No structured research objective (topic string only) | Relevance can't be judged against sub-questions or constraints | Versioned `research_objectives` with sub-questions, tasks, exclusions and constraints |
| Polymorphic `(subject_type, subject_id)` references | No referential integrity; orphaned notes and feedback | `research_items` supertype with real foreign keys; sections and equations referenced explicitly |
| 14 "agents", many of them deterministic | Over-engineering; hard to test; LLM used where code suffices | Split into deterministic **services** and 10 LLM **agents** (AGENT_DESIGN) |
| Five or more infrastructure services in the MVP (Redis, Qdrant, Neo4j planned) | Ops burden for a single-user tool | Postgres + pgvector + GROBID only; adapters later |
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
| OpenAlex | broad metadata, references, OA locations, field-normalised citation context | API key required since Feb 2026 | free daily allowance, then metered; full-text files charged per file; `from_created_date` / `from_updated_date` filters need a paid plan | search precision; costs at scale; version conflation; publication dates unreliable for recency (OpenAlex's own guidance) |
| Crossref | DOI validation, publisher metadata, authoritative publication dates for DOIs, journal-article date-range search | email (polite pool) | free | rare abstracts; topic search precision is low; dates may be month-only or future-dated |
| Unpaywall | OA PDF locations by DOI | email | free | DOI-only; some links are landing pages |
| GROBID | PDF → structured TEI | self-hosted | compute only | weak on tables and formulae; no OCR |
| Hugging Face Hub | models, datasets, paper links | optional token | free | links depend on authors tagging arXiv IDs |
| GitHub REST | repository metadata and search | token | free | 5,000 req/h; search about 30 req/min |
| LLM API (Anthropic default) | planning, judgements, extraction, explanations, critique | API key | metered (§7) | cost; latency; refusals; needs validation |
| Google Scholar | — | — | — | not used (no API; terms forbid scraping) |
| Papers with Code | — | — | — | discontinued in 2025 |

Rate limits and pricing must be re-verified when each integration is built.
Each integration doc records the verification date.

## 7. Operational cost estimates

**Assumptions** (to be replaced by measurements in R1): Anthropic list prices
as of planning (`claude-opus-5-5` $4 / $20 per million input/output tokens;
`claude-sonnet-5-5` $2 / $10; `claude-haiku-5-5` $0.10 / $0.50). A typical
project has 300 candidate papers, 120 included and 50 analysed in full text.
Prompt caching and batch discounts are not counted, so real costs should be
lower.

| Activity | Token estimate | Opus 5.5 (default) | If Sonnet 5.5 chosen | If Haiku 5.5 chosen |
|---|---|---|---|---|
| Objective + query planning | ~10k in / 3k out | ~$0.10 | ~$0.05 | <$0.01 |
| Stage B relevance judgements (top 150 papers; ~1.5k in / 0.3k out each) | 225k / 45k | ~$1.80 | ~$0.90 | ~$0.05 |
| Cross-checks (~15% of judgements) | 35k / 7k | ~$0.30 | ~$0.15 | <$0.01 |
| Recommendation cards viewed (~60; 3k / 0.8k each) | 180k / 48k | ~$1.70 | ~$0.85 | ~$0.04 |
| Primer + glossary + learning path | ~60k / 20k | ~$0.65 | ~$0.32 | ~$0.02 |
| Ask & Learn session (~30 turns; ~8k in incl. context and evidence / 0.8k out per turn; before prompt-caching savings) | 240k / 24k | ~$1.45 | ~$0.72 | ~$0.04 |
| **R1 MVP project total (setup + one tutor session)** | | **~$6** | ~$3 | ~$0.15 |
| Latest Research weekly scan (Stage B for 60, abstract extraction for 60, ~20 cards viewed, digest) | ~350k / 85k | ~$3.10 | ~$1.55 | ~$0.08 |
| Full-text extraction, 50 papers (~20k in / 3k out each; batch could halve this) | 1M / 150k | ~$7 | ~$3.50 | ~$0.18 |
| Gap investigation + novelty + red-team (R3) | ~2–3M / 0.4M | ~$16–20 | ~$8–10 | ~$0.40 |
| Proposal drafting (R4) | ~0.3M / 60k | ~$2.40 | ~$1.20 | ~$0.06 |

These are order-of-magnitude figures. Model choice per task remains your
decision (decision D1). Quality must be measured with the evaluation
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
| Ask & Learn: evidence search over the user's papers ("show me where this term appears") | ⚠️ passages only, no answers | ✅ full tutor |
| Explanations, equations, exercises, extraction, gaps, ideas, proposals | ❌ | ✅ |

A local open-weight model can be plugged into the gateway for zero API cost.
It is not the default, because extraction and judgement quality must pass the
evaluation gates first.

## 9. Scaling path (not needed for the MVP)

| Trigger | Change |
|---|---|
| Multiple workers or users | add Redis-backed rate limiting, or Postgres advisory locks; authentication |
| More than ~5M chunks, or cross-project semantic search at scale | Qdrant adapter for `VectorStore` |
| Cross-project graph analytics | Neo4j projection for `GraphStore`, rebuilt from Postgres |
| Many concurrent long runs | separate worker pools per workflow type |

## 10. Technical limitations (known and accepted)

- Full text only for legally accessible PDFs and user uploads.
- Very recent papers often lack citation data and Semantic Scholar/OpenAlex
  records for several days; Latest Research relies on arXiv and Crossref
  dates and on content signals for them.
- Fields with little arXiv coverage (e.g. biology, medicine) have weaker
  preprint recall unless additional preprint servers are added (decision
  D22).
- Publisher dates can be month-precision or revised after the fact. Such
  papers appear as "Date uncertain" rather than in the default view.
- Table and formula extraction from PDFs is imperfect. Equations are exact
  only via arXiv LaTeX source.
- Citation intents and contexts are limited to what Semantic Scholar
  provides.
- Index coverage and freshness depend on the external sources.
- LLM judgements are probabilistic. They are mitigated by quotes,
  cross-checks, calibration and user overrides, but not eliminated.
- Compute estimates are only possible when papers report hardware and time.
