# 14. Feature prioritisation, MVP and roadmap (v2)

**Supersedes:** [09-roadmap.md](09-roadmap.md) for ordering and scope. The
detailed Phase 1–2 acceptance criteria in doc 09 are carried into R0 and R1
below unchanged; Phase 3–7 criteria are redistributed into R2–R5.

## 14.1 Prioritisation method

Each feature was scored on:
- **Value to beginners** and **value to experts** (0–3),
- **Differentiation** (0–3; does it make the connected journey real?),
- **Effort** (S/M/L) and **risk** (reliability of the output),
- **Dependencies** (what must exist first).

The MVP must (a) be useful on its own, (b) prove the positioning — a
beginner can go from an unfamiliar topic to reading real papers with
understanding, and an expert gets a trustworthy, persistent collection and
field map — and (c) build the foundations later releases reuse.

## 14.2 Feature prioritisation

| Feature (req IDs) | Beginner | Expert | Diff. | Effort | Risk | Depends on | Release |
|---|---|---|---|---|---|---|---|
| Multi-source discovery, dedup, citation expansion (DIS-1–3) | 3 | 3 | 1 | M | low | — | **R1** |
| Plain-language guided checkpoints, journey bar (DIS-4, UX-1–5) | 3 | 1 | 2 | S | low | discovery | **R1** |
| Topic primer, grounded in surveys (LRN-1) | 3 | 1 | 3 | S | med | discovery, survey role | **R1** |
| Field map v1 from metadata + citations (UND-3 partial) | 3 | 2 | 3 | M | low–med | discovery, embeddings | **R1** |
| Glossary with links to where terms appear (LRN-2) | 3 | 1 | 2 | M | med | discovery | **R1** |
| Learning path with progress (LRN-3) | 3 | 0 | 3 | M | med | glossary, field map | **R1** |
| Level switch on explanations (LRN-4) | 3 | 2 | 3 | S | low | explanation service | **R1** |
| Paper explainer, section by section, OA full text (LRN-5) | 3 | 2 | 2 | M | med | PDF retrieval + GROBID | **R1** |
| Reading status, notes, decisions (PER-1, PER-2) | 2 | 3 | 2 | S | low | — | **R1** |
| Exports: BibTeX, Markdown discovery report | 1 | 3 | 0 | S | low | discovery | **R1** |
| Full-text extraction: methods/datasets/metrics/results/limitations/assumptions (UND-1) | 1 | 3 | 1 | L | high | PDF pipeline | R2 |
| Equation explainer via arXiv LaTeX (LRN-6) | 3 | 2 | 2 | M | med | section explainer | R2 |
| Algorithm/architecture explainer (LRN-7) | 3 | 2 | 2 | S | med | extraction | R2 |
| Coding exercises, "not run" (LRN-8) | 3 | 0 | 2 | S | med | Tutor | R2 |
| Comparison tables (CMP-1) | 2 | 3 | 1 | M | med | extraction | R2 |
| Improvements / evolution tracing (CMP-2, CMP-3) | 2 | 3 | 2 | M | med | extraction, citations | R2 |
| Conflicting findings (CMP-4) | 1 | 3 | 2 | M | high | results extraction | R2 |
| Protocols, compute reports (UND-2) | 0 | 3 | 1 | M | high | extraction | R2 |
| Field map v2 with methods/datasets per direction (UND-3, UND-4) | 2 | 3 | 2 | S | low | extraction | R2 |
| Gap Detective with for/against evidence (INV-1–4) | 1 | 3 | 3 | L | high | R2 extraction | R3 |
| Hypotheses, novelty check, red-team, ranking (VAL-1–4) | 1 | 3 | 3 | L | high | gaps | R3 |
| Idea tracking (PER-3) | 1 | 3 | 2 | S | low | hypotheses | R3 |
| Datasets/baselines/metrics recommendations, ablations, compute estimates (INN-1, 2, 4, 5) | 1 | 3 | 2 | M | med | R2 | R4 |
| Implementations: GitHub + Hugging Face (INN-3) | 1 | 3 | 1 | M | low | R1 | R4 |
| Experiment plans, proposals, literature review report, LaTeX/PDF (INN-6) | 1 | 3 | 1 | L | med | R3 | R4 |
| Experiment tracking (PER-4) | 0 | 3 | 1 | S | low | — | R4 |
| Monitoring + impact alerts (PER-5, PER-6) | 1 | 3 | 3 | M | med | events, gaps | R5 |
| Executed (sandboxed) exercises | 2 | 0 | 1 | M | med | exercises | R5+ |
| Cross-project discovery, knowledge graph store, auth/multi-user | 1 | 2 | 1 | L | low | — | R5+ |

## 14.3 The MVP (R0 + R1): "Discover & Learn"

**One-sentence goal:** a user enters an unfamiliar topic and, within one
session, has a deduplicated, cited collection of the right papers, a map of
the field, a primer and glossary at their level, an ordered reading path, and
can read open-access papers section by section with explanations — and all of
it is still there next week.

**In scope**
- Discovery (Milestone 1 from doc 09) with plain-language checkpoints and
  survey detection.
- Field map v1 (metadata + citation communities + embeddings).
- Topic primer, glossary, learning path, level switching.
- PDF retrieval (arXiv, S2 OA, OpenAlex OA, Unpaywall) + GROBID sectioning
  for papers the user opens or that are on the learning path; "Read with me"
  section explainer.
- Project persistence: reading status, notes, decisions, learning path
  progress, journey bar with next step.
- Exports: discovery report (Markdown), BibTeX.

**Explicitly out of the MVP:** full-text structured extraction, comparison
tables, equations, exercises, gap detection, hypotheses, experiment design,
code links, monitoring, LaTeX/PDF export, auth.

**Why this MVP:** it is the smallest slice that delivers the positioning
("from beginner…") for real users while building every foundation the
"…to creator" releases need: the research record, provenance, PDF pipeline,
explanation service with claim validation, events, journey registry and
project memory. Expert users already get value (deduplicated cited
collection, field map, reading/annotation workspace), and nothing in R1 is
throwaway.

## 14.4 MVP acceptance criteria

All Phase 1 and Phase 2 criteria from doc 09 apply (infrastructure, dedup,
provenance, rate limits, checkpoints, reproducibility, exports, e2e). In
addition:

### Setup and guidance
- [ ] A new project needs only topic, level and objective; all other options have defaults and are hidden under "Advanced options".
- [ ] The journey bar shows all seven stages with status (ready / in progress / not yet available) and exactly one recommended next step, computed from project data (unit-tested per objective).
- [ ] An automated UI string check confirms that default (non-"How was this found?", non-Settings) screens contain none of: agent, embedding, vector, LangGraph, LLM, token, API key, prompt.
- [ ] Every long-running step shows plain-language progress within 2 seconds of starting and updates at least every 10 seconds while work is happening.

### Evidence and labelling
- [ ] 100% of AI-written blocks carry one of the four claim-kind badges; an API-level test fails any explanation response containing an unlabelled block.
- [ ] Grounded explanations: every reference resolves to a project paper; every quote verifies against the stored text (same rules as doc 04 §4.7).
- [ ] Background explanations contain no citations, paper titles or numeric results unless they resolve to project papers (validator test with adversarial fixtures).
- [ ] When full text is unavailable, the paper explainer states the reason in one sentence, explains the abstract only (labelled "Based on the abstract only"), and offers PDF upload.

### Learning features
- [ ] **Primer:** generated at each of the three levels for the 5 reference topics; ≥ 80% of its sentences that describe the field are grounded in project papers (measured by the validator), the rest labelled background.
- [ ] **Glossary:** ≥ 15 terms for each reference topic; every term links to ≥ 1 verified span in a project paper where it appears.
- [ ] **Learning path:** every item has a rationale; no item appears before one of its recorded prerequisites; marking items done persists and updates the next step.
- [ ] **Level switch:** switching level on an explanation returns a different cached explanation for the same subject; the second request for the same (subject, level) is served from cache (no LLM call; asserted in tests).
- [ ] **Section explainer:** for open-access test papers, sections and page numbers match GROBID output; each section explanation links back to the section; explanations of sections the user never opens are never generated (cost control, asserted).

### Field map
- [ ] For each reference topic: 3–8 directions; each with ≥ 3 papers, a label, the signals that formed it, and its foundational and recent papers with reasons.
- [ ] Frequent authors per direction are computed counts from project data (no LLM).
- [ ] Recomputing the map with the same paper set and settings gives the same clusters (fixed seeds).

### Persistence
- [ ] Reading status, notes, decisions and learning-path progress survive restarts and appear in Project History.
- [ ] Adding papers to the project emits `paper.added_to_project` events; the consumer invalidates affected cached outputs (field map flagged stale, primer flagged "new papers since this was written").

### Usability (manual, before release)
- [ ] 5 participants new to research each complete: create project → approve plan → read the primer → open the first learning-path paper → read one section explanation, **without assistance**, and can say what the field's main areas are afterwards.
- [ ] 3 experienced researchers rate the discovery collection and field map for their own topic; any wrong or fabricated item found is logged as a release-blocking bug if it is a fabrication.

## 14.5 Updated roadmap

| Release | Theme | Contents | Old phases it absorbs |
|---|---|---|---|
| **R0** | Foundation | Repo, FastAPI, React shell, Postgres (+pgvector), Postgres job queue, SSE, Docker, CI, journey registry skeleton, claims model v2, domain events table | Phase 1 |
| **R1 (MVP)** | Discover & Learn | Discovery (Milestone 1) + surveys; field map v1; Tutor (primer, glossary, sections) with level switching and cache; learning path; PDF retrieval + GROBID sections; reading status, notes, decisions; journey guidance; Markdown/BibTeX export | Phase 2, part of Phase 3, part of Phase 4 (directions), part of Phase 7 (memory) |
| **R2** | Understand & Compare | Full extraction (methods, datasets, metrics, results, limitations, assumptions, protocols, compute); equations via arXiv LaTeX; algorithm explainer; exercises (not run); comparison tables; improvements/evolution; conflicts; field map v2 | Rest of Phase 3, part of Phase 4 |
| **R3** | Investigate & Validate | Gap Detective with overlap + contradiction probes, for/against evidence; hypotheses; novelty verification; red-team; ranking; idea tracking | Phase 4 |
| **R4** | Innovate | Experiment intelligence (baselines, metrics, ablations, compute estimates); GitHub + Hugging Face links; experiment plans; proposals; literature review report; LaTeX/PDF export; experiment tracking | Phases 5 and 6 |
| **R5** | Persist & Monitor | Scheduled monitoring; impact alerts on gaps/ideas/experiments; incremental updates; optional sandboxed exercise execution; cross-project discovery; auth; optional Qdrant/Neo4j adapters if scale needs them | Phase 7 |

### R1 build order (each step a PR with tests)
1. R0 scaffold (two PRs, as planned in doc 09).
2. Identifier normalisation, `SourceClient`, arXiv / S2 / OpenAlex / Crossref clients.
3. Paper schema, dedup, enrichment, discovery workflow with checkpoints (plain-language + advanced views).
4. Report builder + exports; Paper Explorer, Saved Papers, Project History.
5. Claims v2 + `ClaimValidator`; explanation service with cache and streaming; topic primer.
6. Embeddings (pgvector) + field map workflow + field map UI.
7. Glossary + concept graph + learning path + UI.
8. PDF resolver chain + GROBID + "Read with me" section explainer.
9. Journey Guide + journey bar + next-step card; notes and decisions UI.
10. Usability round; fix; release.

### Acceptance criteria for R2–R5
Carried over from doc 09 (Phase 3 → R2, Phase 4 → R3, Phases 5–6 → R4,
Phase 7 → R5), with these additions:
- **R2:** equation explanations quote the paper's own symbol definitions when present and label inferred meanings; exercises always show "not run"; comparison cells link to evidence or say "not reported"; every `paper_relations` row has evidence spans; conflicts show a comparability check.
- **R3:** every gap has both an overlap probe and a contradiction probe with recorded queries; the gap view shows evidence for and against side by side; user decisions on ideas are logged with reasons.
- **R4:** compute estimates appear only when backed by `compute_reports` rows, otherwise "insufficient information"; ablation suggestions are labelled AI interpretation and tied to named method components; user-reported experiment results are never displayed alongside paper-reported results without a distinguishing label.
- **R5:** an impact alert always includes the new paper, the affected gap/idea/experiment, and the overlapping passage; dismissing an alert is logged; monitors are idempotent.

## 14.6 Revised decisions

These are added to or replace entries in [00-index.md](00-index.md).

| # | Decision | Recommendation |
|---|---|---|
| D3 (revised) | Job queue | Postgres-backed queue + `LISTEN/NOTIFY`; no Redis in the MVP |
| D12 | Vector store | pgvector behind a `VectorStore` interface; Qdrant later if needed |
| D13 | Knowledge graph store | Postgres + `networkx`; Neo4j deferred |
| D14 | Claim taxonomy | Four kinds (reported finding, extracted observation, AI interpretation, unverified hypothesis) + grounding for AI interpretations |
| D15 | Explanations | On-demand, cached per (subject, level, prompt version); never pre-generated in bulk |
| D16 | Equations | arXiv LaTeX source first; user selection otherwise; no PDF math OCR in R2 |
| D17 | Exercises | Generated but not executed until a sandbox exists; status always shown |
