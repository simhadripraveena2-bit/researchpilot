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
| `paper.dates_updated` / `paper.match_decided` | release-type reclassification for affected scan entries |
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
unreliable for finding recent records. The `DateResolver` service therefore
stores **every date claim separately**, then derives a first public date and
a release type with explicit confidence.

**1. Collect date claims** (`paper_dates`, one row per claim, never
overwritten). Each claim records: date type, value, precision
(timestamp/day/month/year), the **manifestation** it belongs to (preprint or
published version) and its identifier, source, source record, and retrieval
time.

| Source | Field | Stored as date type | Role |
|---|---|---|---|
| arXiv | `published` (v1 submission timestamp, UTC) | `preprint_v1_submitted` | **authoritative** first preprint date |
| arXiv | per-version submission dates | `version_submitted` (+ version) | authoritative for that version |
| arXiv | `updated` | `latest_version_submitted` | version event only |
| bioRxiv / medRxiv | `date` of version 1 (from `/details`) | `preprint_v1_posted` | **authoritative** first preprint date (day precision) |
| bioRxiv / medRxiv | `date` of later versions | `version_posted` (+ version) | authoritative for that version |
| bioRxiv / medRxiv | `/pubs` published date | `published_online` (published manifestation) | supporting; confirmed via Crossref when possible |
| Crossref | `published-online`, `published-print`, `issued` | `published_online`, `published_print`, `issued` | **authoritative** (precision checked) |
| Crossref | `posted` (posted-content, e.g. preprints with DOIs) | `preprint_posted` | authoritative for that preprint |
| Crossref | `created`, `deposited`, `indexed` | `metadata_created`, `metadata_deposited`, `metadata_indexed` | ❌ never a publication date |
| OpenAlex | `publication_date` | `openalex_publication_date` | **secondary** |
| OpenAlex | `created_date` | `index_created` | "newly indexed" detection only |
| OpenAlex | `updated_date` | `metadata_updated` | ❌ never |
| Semantic Scholar | `publicationDate` | `s2_publication_date` | **secondary** (often missing or year-only) |
| ResearchPilot | first time we saw the paper | `first_seen_by_researchpilot` | "newly indexed" fallback only |

**2. Derive the first public date and its confidence** (decision **D28**):

| `date_confidence` | Rule | Allowed in *New research*? |
|---|---|---|
| `verified` | Earliest authoritative claim at day (or timestamp) precision, with no authoritative claim disagreeing by more than 2 days | ✅ |
| `corroborated` | No authoritative claim, but **two independent secondary sources** (OpenAlex and Semantic Scholar) agree within ±1 day at day precision | ✅ with the badge "Date from secondary sources (corroborated)" |
| `single_secondary` | Only one secondary source gives a day-precision date | ❌ → **Date uncertain** (default) |
| `conflicting` | Authoritative claims disagree by more than 2 days, or two secondary sources disagree by more than 1 day with no authoritative claim | ❌ → Date uncertain (all claims shown) |
| `uncertain` | Only month/year precision, a future date, or no claim | ❌ → Date uncertain |

Before settling on `single_secondary`, the resolver tries to corroborate: a
Crossref lookup when a DOI is known, an arXiv lookup when an arXiv ID is
known, and a bioRxiv/medRxiv lookup for their DOIs. A secondary claim that
disagrees with an authoritative claim is kept and flagged, but it doesn't
create a conflict: the authoritative claim wins.

**3. Classify the release type** relative to the window `[start, end)`
(decision **D25**):

| Release type | Rule |
|---|---|
| New preprint | First preprint version (arXiv v1, or bioRxiv/medRxiv v1) in window, `verified` or `corroborated` |
| New publication | Published-version date in window **and** no earlier linked version |
| Published version of an earlier preprint | Published-version date in window **and** a matched earlier preprint (D29); shown with the preprint date |
| Revised version of an older paper | A new version (v2+) in window **and** first public date before the window |
| Older paper newly indexed | First public date before the window **and** first indexed in window (OpenAlex `created_date` when that capability is enabled, otherwise our first-seen date, labelled) |
| Date uncertain | The date that would place it in the window is `single_secondary`, `conflicting` or `uncertain` |

Rules that always apply:
- A metadata-change date never makes a paper "new".
- Month- or year-precision dates never fall inside a window of 31 days or
  less.
- Future dates (beyond retrieval time + 1 day) are flagged and treated as
  uncertain.
- Release types are recomputed when new date claims or matches arrive
  (`paper.dates_updated`, `paper.match_decided`). A changed type is shown
  with "Reclassified", never silently swapped.
- arXiv's v1 timestamp is the submission time, and announcement can lag 1–3
  days. Dates are labelled "v1 submitted", and scans fetch 3 extra days
  before the window start so late announcements aren't missed. Inclusion is
  still decided by the submission time.

**4. Time zones** (decision **D23**):
- **Storage and computation in UTC.** Timestamps are `timestamptz`. Rolling
  windows are computed in UTC: `[now_utc − N×24 h, now_utc)`, start
  inclusive and end exclusive.
- **Date-only claims** (Crossref day dates, bioRxiv dates) are stored as
  calendar dates with `precision = day` and are **never shifted across time
  zones**. A date-only claim *D* is treated as the UTC day `[D 00:00, D+1
  00:00)`. It is in the window if that day overlaps the window. If the day
  is only partly inside (the boundary day), the entry is flagged
  `boundary_day` and the provenance popover says so.
- **Display in the user's local time zone.** IANA zone from the browser,
  overridable in Settings and stored on the user. Timestamps (e.g. arXiv
  submission) are converted for display ("Submitted Nov 9, 00:30 CET").
  Date-only values are shown as the date itself, without conversion. Window
  bounds are shown in local time ("Nov 3, 14:00 – Nov 10, 14:00 CET"). DST
  transitions are handled by the zone database, never by fixed offsets.

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
- A match never deletes anything. Identifiers, `source_records` and
  `paper_dates` keep their source and manifestation, so the preprint's v1
  date and the journal's publication date both survive in one work.
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
     medRxiv entries carry a "Preprint — not peer-reviewed" label.
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
     for journal articles, and DOI lookups to confirm or corroborate dates
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

### 4.11 API additions for these features

| Method | Path | Purpose |
|---|---|---|
| GET | `/projects/{id}/latest` | entries for a window: `from`, `to` (default rolling 7 d, UTC), `release_type`, `subtopic`, `method`, `source`, `tier`, `action`, `oa`, `status`; includes coverage, the last scan and the display time zone |
| POST | `/projects/{id}/latest/scans` | start a scan for a window → `202 {run_id, scan_id}` |
| GET | `/latest/scans/{scan_id}` | scan status, coverage, failures, counts by release type |
| GET | `/projects/{id}/latest/digest?scan_id=` | "What's new" digest (grounded, cached per scan and level) |
| GET | `/projects/{id}/latest/{paper_id}/brief` | the eight-question Latest brief |
| PATCH | `/projects/{id}/items/{item_id}` | save, dismiss (+ reason), read later, tags (shared with other pages) |
| GET | `/papers/{id}/dates` | all date claims with sources and manifestations, the derived first public date, confidence and release-type history |
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
| OpenAlex | broad metadata, references, OA locations, field-normalised citation context | API key required since Feb 2026 | free daily allowance, then metered; full-text files charged per file; `from_created_date` / `from_updated_date` filters need a paid plan (not required: enabled later via `OPENALEX_CAPABILITIES`) | search precision; costs at scale; version conflation; publication dates unreliable for recency (OpenAlex's own guidance) |
| Crossref | DOI validation, publisher metadata, authoritative publication dates for DOIs, journal-article date-range search | email (polite pool) | free | rare abstracts; topic search precision is low; dates may be month-only or future-dated |
| Unpaywall | OA PDF locations by DOI | email | free | DOI-only; some links are landing pages |
| bioRxiv / medRxiv API (`api.biorxiv.org`) | life-science preprints by date range (`/details`), preprint → published links (`/pubs`) | no key | free | no full-text search (category + local text filtering); no published rate limit (client uses 1 req/s); medRxiv preprints are not peer-reviewed |
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
| Progressive lesson on one concept (8 steps, ~6k in / 0.8k out each; cached steps are free on reuse) | 48k / 6.4k | ~$0.32 | ~$0.16 | <$0.01 |
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
| Cross-project graph analytics | Neo4j projection for `GraphStore`, rebuilt from Postgres |
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
- Papers dated only by one secondary source go to "Date uncertain" (D28).
  This lowers recall for venues absent from arXiv, bioRxiv/medRxiv and
  Crossref, by design.
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
