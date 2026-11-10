# 11. Architecture v2 — incorporating the product vision

**Amends:** [02-system-architecture.md](02-system-architecture.md),
[03-database-schema.md](03-database-schema.md),
[04-agents-and-workflows.md](04-agents-and-workflows.md). Anything not
mentioned here is unchanged.

## 11.1 Review of the v1 architecture against the vision

| Vision feature | Already covered by v1? | What is missing |
|---|---|---|
| Discovery | Yes (Milestone 1) | Plain-language checkpoints; "survey" role |
| Learning mode / learning assistant | **No** | Audience level, explanations, glossary, prerequisites, learning paths, equations, exercises |
| Field Navigator | Partly (Phase 4 directions + taxonomy) | Needs to work **early** from metadata + citations (before full-text analysis); key researchers; direction relationships |
| Paper-to-paper intelligence | Mostly (comparison matrix, conflicts) | Evolution tracing; "improves on" relations; assumptions |
| Gap Detective | Yes (Phase 4 pipeline) | Explicit contradicting-evidence search per gap (v1 only searched for overlap) |
| Benchmark & experiment intelligence | Partly | Protocols, baselines, ablations, compute reports |
| Persistent projects | Partly (monitors, memory in Phase 7) | Reading status, decision log, idea/experiment tracking, impact alerts |
| Simple UX | Partly | Journey stages, objective-driven guidance, hiding internals |

**Conclusion:** the core of v1 — one evidence-linked research record,
typed agents, durable workflows, provenance everywhere — fits the vision
well. The vision needs **one new capability** (audience-aware, on-demand
explanation) and **a few new record types**. It does not need new
infrastructure. In fact the plan below *removes* infrastructure from the MVP.

## 11.2 Seven architectural decisions that keep future features cheap

These are the decisions that let later releases add features without
rewriting earlier ones.

### A1. One research record; features are views or generators over it
Every feature reads the same tables (papers, citations, documents, evidence
spans, entities, claims). New features add tables that *reference* the record;
they never copy papers or keep private stores. Example: the learning path
points at `papers`, `entities(type=concept)` and `document_sections`; the
field map points at `research_directions`. Adding "Compare" later reuses the
same extractions the learner already sees.

### A2. Audience is a parameter, not a pipeline
`AudienceProfile {level, objective}` is passed into generation calls and UI
defaults. There is one discovery pipeline, one extraction pipeline, one gap
pipeline. Level affects only (a) the explanation prompt variant and (b) which
fields are shown by default. This avoids three parallel products.

### A3. Two execution modes: batch workflows and on-demand generation
- **Batch workflows (LangGraph, worker):** long, multi-step, checkpointed
  jobs — discovery, full-text analysis, field mapping, gap investigation,
  monitoring.
- **On-demand generation (API, streamed):** short requests triggered by a
  click — "explain this section at beginner level", "define this term",
  "explain equation 3". These are a single structured LLM call plus
  validation, streamed to the browser and **cached** in `explanations` keyed by
  `(subject, level, prompt_version)`. They do not go through LangGraph.

This keeps the learning features fast and cheap (nothing is pre-generated for
papers nobody opens) and keeps LangGraph for what it is good at.

### A4. Polymorphic subject references
Explanations, notes, decisions, claims, alerts and feedback all point at a
`(subject_type, subject_id)` pair where `subject_type ∈ {paper, section,
equation, entity, direction, gap, hypothesis, experiment, comparison, …}`. A
new feature that wants "notes on X" or "explain X" gets them by registering a
subject type — no new tables.

### A5. Four claim kinds + grounding, enforced in one place
The `claims` model (doc 10 §10.5) and a single `ClaimValidator` service are
used by every generator. New generators cannot bypass labelling, because the
API serialises claims only through the validator.

### A6. Domain events (transactional outbox)
Writes that matter emit a row in `domain_events` in the same transaction
(`paper.added_to_project`, `document.parsed`, `gap.opened`,
`hypothesis.status_changed`, `experiment.created`, …). Consumers are small
jobs: invalidate cached explanations, recompute field map, check impact on
open gaps, (later) sync the knowledge graph. Monitoring and impact alerts
(PER-5/6) are therefore *consumers added later*, not changes to existing code.

### A7. Declarative journey stages
Stages are defined in a registry, not hard-coded in the UI:

```python
Stage(
  key="compare",
  title="Compare",
  ready_when=lambda s: s.analysed_papers >= 5,       # computed from the record
  recommended_for={"review_literature", "find_gap"},
  primary_action=Action("start_workflow", "analysis"),
  pages=["/projects/:id/compare"],
)
```

Stage readiness is **derived** from the record (counts, statuses), not
stored, so it can never drift from the data. The UI renders the journey bar
and "next step" card from `GET /projects/{id}/journey`. Adding a stage or
changing guidance is a registry change.

## 11.3 Infrastructure simplifications (MVP)

The vision increases features; the MVP should reduce moving parts.

| v1 plan | v2 recommendation | Why | When to revisit |
|---|---|---|---|
| Redis + arq for jobs, rate limits, pub/sub (D3) | **Postgres-only:** a Postgres-backed job queue (e.g. `procrastinate`), rate-limit state in-process (single worker) and `LISTEN/NOTIFY` for progress events | One fewer service; Postgres already required | Multiple workers or high event volume |
| Qdrant for vectors | **pgvector in Postgres** behind a `VectorStore` interface; Qdrant adapter later | Project-scale corpora (hundreds–low thousands of papers, tens of thousands of chunks) are well within pgvector's range; one database to back up | Cross-project semantic search at large scale |
| Neo4j in Phase 7 | **Deferred indefinitely.** Field maps, prerequisite graphs and citation lineage use Postgres tables + recursive CTEs + in-memory `networkx` | Graph sizes per project are small | Cross-project graph analytics |
| GROBID | Kept (needed for section-by-section explanation in the MVP) | | |

MVP services: `postgres` (with pgvector), `grobid`, `api`, `worker`,
`frontend`. The interfaces (`JobQueue`, `VectorStore`, `GraphStore`) are kept
so the original choices can be plugged in later without touching agents.

## 11.4 Updated component view

```
                 ┌──────────────────────── frontend ─────────────────────────┐
                 │ Journey bar · Guided pages · Explain panel · Evidence drawer│
                 └───────────────┬──────────────────────────────┬────────────┘
                 REST            │                              │ SSE / streamed explanations
┌────────────────────────────────▼──────────────────────────────▼────────────┐
│ api                                                                         │
│  routers ─ Journey service (stage registry, next-step)                      │
│          ─ Explanation service (on-demand, cached, streamed)  ◀── A3         │
│          ─ Project memory service (notes, decisions, ideas, experiments)    │
│          ─ ClaimValidator / CitationValidator                 ◀── A5         │
└──────┬──────────────────────────────────────────────────────────────────────┘
       │ enqueue (Postgres queue)
┌──────▼──────────────────────────────────────────────────────────────────────┐
│ worker                                                                      │
│  LangGraph workflows: discovery · analysis · field_map · investigate ·      │
│                       experiment_design · report · monitor                  │
│  Event consumers (outbox): cache invalidation · field map refresh ·         │
│                            impact detection                   ◀── A6         │
└──────┬───────────────────────────────┬──────────────────────────────────────┘
       ▼                               ▼
  PostgreSQL + pgvector            GROBID · external APIs · LLM API
```

## 11.5 Learning-specific technical choices

- **Equations.** GROBID's formula extraction is unreliable. For arXiv papers,
  fetch the LaTeX source (`arxiv.org/e-print/<id>`) and extract display
  equations with their labels and surrounding text — exact and cheap. For
  other papers, the user can select an equation region in the PDF viewer; the
  selected text (or, later, an image passed to a vision-capable model) is
  explained and stored with `source=user_selection`. Every equation
  explanation quotes the paper's own symbol definitions where the text
  provides them, and labels any symbol meaning it inferred.
- **Terminology.** Candidate terms come from extracted entities and
  noun-phrase statistics over the project's abstracts/sections (terms frequent
  in this corpus but rare in general text). Each term links to the spans where
  it appears; the definition is `ai_interpretation` (grounded when it
  paraphrases a definition found in a paper, background otherwise).
- **Prerequisites.** Edges between concepts are proposed by the LLM
  (`ai_interpretation`) and strengthened when supported by evidence (a paper
  defines B in terms of A; survey sections order them). Learning paths are a
  topological order over the project's concept graph, interleaved with papers
  chosen by role (survey → foundational → recent) and the user's level.
- **Exercises.** Generated as small, self-contained snippets with expected
  output; stored with `verification_status=not_run`. A later release can run
  them in a sandboxed container and update the status.
- **Survey detection.** Add `survey` as a paper role (from publication type,
  title cues and S2/OpenAlex type fields); surveys are the main grounding
  source for primers and learning paths.

## 11.6 Database schema changes

New and changed tables relative to doc 03. Grouped by the release that
introduces them (releases in doc 14).

### Changed (R1)
- `projects`: add `expertise_level enum(beginner, intermediate, advanced)`,
  `objective enum(learn_field, review_literature, find_gap, plan_experiment,
  track_field)`.
- `project_papers`: add `reading_status enum(unread, to_read, reading, read,
  skipped)`, `last_read_section_id`, `read_at`. Add `survey` to `roles`.
- `claims.kind` becomes `enum(reported_finding, extracted_observation,
  ai_interpretation, unverified_hypothesis)`; add `grounding enum(grounded,
  background) null` (required when kind = ai_interpretation).
- `entities.type`: add `concept`, `term`.

### New in R1 (MVP)
| table | key columns | purpose |
|---|---|---|
| `user_profile` | `id, default_level, preferences jsonb` | single-user defaults (multi-user later) |
| `explanations` | `id, subject_type, subject_id, level, content jsonb (blocks with claim ids), status, model, prompt_id, prompt_version, input_hash, created_at`; **UNIQUE (subject_type, subject_id, level, prompt_version, input_hash)** | cached on-demand explanations (A3) |
| `explanation_feedback` | `explanation_id, rating enum(helpful, unclear, wrong), comment, created_at` | quality signal; "wrong" hides the explanation pending regeneration |
| `glossary_terms` | `id, project_id, entity_id, salience numeric, first_paper_id` | project-specific glossary (definition lives in `explanations`) |
| `concept_prerequisites` | `concept_id, prerequisite_id, basis enum(ai_interpretation, paper_evidence), evidence_span_id null, confidence` | prerequisite graph |
| `learning_paths` | `id, project_id, level, version, created_at` | |
| `learning_path_items` | `path_id, ordinal, item_type enum(concept, paper, section, exercise), subject_id, rationale, status enum(todo, done, skipped)` | ordered reading/learning plan with progress |
| `research_directions` (moved earlier from Phase 4) | as doc 03 + `basis jsonb` (which signals formed it) | field map clusters |
| `direction_relations` | `direction_a, direction_b, relation enum(shares_methods, cites, shares_datasets), weight, signal jsonb` | map edges |
| `notes` | `id, project_id, subject_type, subject_id, body, created_at` | user notes on anything (A4) |
| `decisions` | `id, project_id, subject_type, subject_id, decision text, rationale, created_at` | decision log (PER-2) |
| `domain_events` | `id bigserial, type, subject_type, subject_id, payload jsonb, created_at, processed_at` | outbox (A6) |

### New in R2
| table | purpose |
|---|---|
| `equations` (`paper_id, document_id, section_id, label, latex, context_text, source enum(arxiv_latex, grobid, user_selection), page, evidence_span_id`) | equation explainer |
| `assumptions` (`paper_id, text, evidence_span_id not null`) | compare assumptions |
| `experimental_protocols` (`paper_id, dataset_entity_id, split, baselines uuid[], hyperparameters jsonb, evidence_span_ids uuid[]`) | protocol extraction |
| `compute_reports` (`paper_id, hardware text, quantity, duration text, evidence_span_id not null`) | compute estimates only from reported data |
| `paper_relations` (`from_paper_id, to_paper_id, relation enum(improves_on, extends, contradicts, reproduces, compares_with), basis jsonb, evidence_span_ids uuid[]`) | paper-to-paper intelligence, evolution tracing |
| `exercises` (`id, project_id, subject_type, subject_id, level, language, prompt, starter_code, solution, expected_output, verification_status enum(not_run, passed, failed)`) | practice |

### New in R3–R5
- Phase 4 tables from doc 03 (gaps, probes, hypotheses, reviews, scores,
  novelty checks, experiment plans) — with additions:
  - `gap_probes.probe_kind enum(overlap, contradiction)` — every gap gets both
    kinds of search (INV-3).
  - `hypotheses.user_status enum(proposed, shortlisted, accepted, rejected,
    parked)` + `user_reason` (PER-3).
- `experiments` (`id, project_id, hypothesis_id null, title, status
  enum(planned, running, done, abandoned), plan jsonb, notes, created_at`) and
  `experiment_results` (`experiment_id, metric_entity_id, value, setting,
  kind = 'user_reported'`) — user results never mix with paper-reported ones.
- `monitors` (doc 03) and `impact_alerts` (`id, project_id, paper_id,
  subject_type, subject_id (gap/hypothesis/experiment), overlap_judgement,
  evidence_span_ids, status enum(new, dismissed, acknowledged), created_at`).

## 11.7 Revised agent responsibilities

Changes: four learning/navigation agents added; three narrow agents merged;
a deterministic Journey Guide (not an LLM agent) added. Novelty Verification
and Red-Team stay separate so the critic is independent of the generator.

| # | Agent | Responsibility | Mode | LLM | Release |
|---|---|---|---|---|---|
| 1 | **Research Planner** | Topic + level + objective → search plan and plain-language explanation of the plan | batch | optional | R1 |
| 2 | **Paper Discovery** | Search, normalise, deduplicate, enrich | batch | no | R1 |
| 3 | **Citation Exploration** | References, citations, recommendations; lineage edges | batch | no | R1 |
| 4 | **Field Navigator** *(new; absorbs taxonomy part of Methodology Comparison)* | Subfields from citation communities + embeddings; labels; per-direction foundational/recent papers, methods, datasets, frequent authors; direction relations | batch | labels only | R1 (metadata) → R2 (with extractions) |
| 5 | **Tutor** *(new)* | Explanations of topic, terms, sections, equations, algorithms at a given level; worked examples; exercises; enforces grounding rules | on-demand | yes | R1 (topic, terms, sections) → R2 (equations, algorithms, exercises) |
| 6 | **Learning Path Planner** *(new)* | Concept graph + prerequisite edges → ordered learning path for a level; updates as papers are read | batch (small) | yes | R1 |
| 7 | **Paper Analysis** | Full-text extraction: contributions, methods, datasets, metrics, results, limitations, assumptions, protocols, compute reports, equations | batch | yes | R2 (R1: section structure only) |
| 8 | **Paper-to-Paper Comparison** *(was Methodology Comparison)* | Comparison tables, `paper_relations` (improves on / extends / contradicts), evolution timelines, conflicting findings | batch + on-demand tables | yes | R2 |
| 9 | **Benchmark & Experiment Intelligence** *(merges Dataset & Benchmark + Metrics Analysis)* | Dataset/task/metric catalogues, standard baselines, recommended metrics, protocols, ablation suggestions, compute estimates from reports, code/HF links | batch | light | R2 (catalogue) → R4 (experiment design) |
| 10 | **Gap Detective** *(was Research Gap Discovery)* | Gap pipeline (doc 04 §4.6) + contradiction probes + for/against evidence | batch | partly | R3 |
| 11 | **Novelty Verification** | Independent searches for prior work | batch | judgement only | R3 |
| 12 | **Red-Team Reviewer** | Adversarial critique with own search budget | batch | yes | R3 |
| 13 | **Research Proposal** | Experiment plans and proposals from accepted hypotheses | batch | yes | R4 |
| 14 | **Project Monitor** *(new)* | Scheduled searches; impact detection on gaps/ideas/experiments via events | batch (scheduled) | judgement only | R5 |
| — | **Journey Guide** *(deterministic service)* | Computes stage readiness and the next recommended step from the record | sync | no | R1 |

All agents keep the v1 contract (typed input/output, injected dependencies,
evidence on every output). On-demand agents (Tutor, comparison tables) use the
same `Agent` protocol; only the caller differs (API instead of a graph node).

## 11.8 Workflow changes

- **Discovery workflow** (doc 04 §4.4A): checkpoints rewritten in plain
  language; adds `detect_surveys` to role classification; on completion emits
  `discovery.completed`, which triggers the **field map** workflow.
- **New: field map workflow** (R1): embeddings of title+abstract (pgvector) →
  citation graph communities (Leiden on bibliographic coupling + direct
  citations) → combine → LLM labels from member titles → per-direction
  statistics (deterministic) → direction relations.
- **New: learning setup workflow** (R1): term candidates → glossary →
  concept graph + prerequisites → learning path for the project's level.
  Explanations themselves are generated lazily on demand.
- **Analysis workflow** (R1 partial / R2 full): R1 runs PDF retrieval +
  GROBID sectioning only for papers on the learning path or opened by the
  user; R2 adds full extraction.
- **Gap workflow** (R3): each gap gets an overlap probe and a contradiction
  probe; results populate for/against evidence.
- **Monitor workflow** (R5): scheduled discovery delta → `paper.added_to_project`
  events → impact detection consumer.

## 11.9 API additions

| Method | Path | Release |
|---|---|---|
| GET | `/projects/{id}/journey` — stages, readiness, next step | R1 |
| POST | `/explanations` — `{subject_type, subject_id, level}` → cached or streamed new explanation | R1 |
| GET | `/explanations/{id}`; POST `/explanations/{id}/feedback` | R1 |
| GET | `/projects/{id}/primer?level=` | R1 |
| GET | `/projects/{id}/glossary`; GET `/glossary/{term_id}?level=` | R1 |
| GET/POST | `/projects/{id}/learning-path` (get / regenerate); PATCH item status | R1 |
| GET | `/projects/{id}/field-map`; GET `/directions/{id}` | R1 |
| GET | `/papers/{id}/sections` (with explain links) | R1 |
| GET/POST | `/projects/{id}/notes`, `/projects/{id}/decisions` | R1 |
| GET | `/papers/{id}/equations`; POST `/papers/{id}/equations` (user selection) | R2 |
| POST | `/projects/{id}/comparisons` — `{paper_ids, attributes}` → table | R2 |
| GET | `/projects/{id}/evolution?direction=` | R2 |
| GET | `/projects/{id}/conflicts` | R2 |
| GET | `/gaps/{id}/evidence` — for/against | R3 |
| PATCH | `/hypotheses/{id}/status` | R3 |
| CRUD | `/projects/{id}/experiments` | R4 |
| GET | `/projects/{id}/alerts`; PATCH alert status | R5 |
