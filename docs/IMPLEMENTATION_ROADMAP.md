# Implementation Roadmap

**Status:** canonical. It supersedes `docs/plan/09` and `docs/plan/14`.

## 1. Repository audit (as of 2026-11-10, re-checked at the final architecture review)

### 1.1 What exists
| Area | Status |
|---|---|
| Source code (backend, frontend) | **None.** No Python, TypeScript or configuration files |
| Database models / migrations | **None** |
| API endpoints | **None** (designed in `docs/plan/05-api.md`) |
| Agent implementations | **None** (designed in docs) |
| Tests / CI | **None** |
| Docker / deployment | **None** |
| Documentation | `README.md`; 15 planning documents in `docs/plan/` (two planning rounds); this set of nine canonical documents in `docs/` |

The only branch is `claude/eloquent-galileo-cmyek5`. All of its commits are
documentation; no application code has been added since. Everything below is therefore a comparison of the **plan**
against the full vision. There is no code to refactor.

### 1.2 Plan coverage against the full vision
| Vision area | Covered in earlier plan | Missing before this revision |
|---|---|---|
| DISCOVER | Detailed (Milestone 1) | Objective model; seeds chosen by usefulness rather than citations |
| LEARN | Designed in v2 (primer, glossary, path, levels) | Learning resources chosen by RIE |
| UNDERSTAND | Designed (full text, extraction, field map) | Typed dataset/model attributes |
| **FILTER** | **Not a stage**; a single relevance score + date/citation roles | **Research Intelligence Engine** (dimensions, cards, tiers, overrides, feedback) |
| COMPARE | Designed | Resource comparisons via cards |
| INVESTIGATE | Designed (gap pipeline) | Contradiction probes (added in v2), gap assessment by RIE |
| VALIDATE | Designed | Idea assessment by RIE |
| EXPERIMENT | Partly (Phase 5 links) | Constraint-aware resource selection; experiment tracking |
| PROPOSE | Designed (reports) | — |
| Verification of classifications | Quote/citation checks only | Signal provenance, cross-checks, calibration, claim verification levels |
| Evaluation | Extraction eval only | Gold sets for relevance, explanations, structure; beat-the-proxy test; release gates |
| Costs & free operation | Not estimated | Cost model; free-source mode |
| Latest Research | Only "latest" as a paper role inside discovery (by date) | Dedicated page, date provenance, release types, recurring scans |
| Ask & Learn | One-shot explanations only | Conversations, context, scope, styles, follow-ups, prerequisites, saving |

Weaknesses in the earlier plan and their fixes are listed in
[ARCHITECTURE §5](ARCHITECTURE.md#5-weaknesses-of-the-previous-plan-and-how-this-version-addresses-them).

## 2. Feature dependency graph

```mermaid
graph TD
  F0[R0 Foundation: repo, API, worker, Postgres+pgvector, events, journey registry, claims model]
  D1[Source clients + provenance + cache]
  D2[Dedup + enrichment + citations]
  OBJ[Research objective model + Planner]
  RA[RIE Stage A: deterministic signals, tiers, anti-proxy rules]
  RB[RIE Stage B: relevance judgements + cross-checks]
  CARD[Recommendation cards + overrides + feedback]
  FM[Field map]
  PDF[PDF pipeline + GROBID sections]
  EXPL[Explanation service: primer, glossary, sections, levels]
  LP[Learning path]
  EXT[Full-text extraction]
  ENT[Typed entities: methods, datasets, metrics]
  EQ[Equations via arXiv LaTeX]
  CMP[Comparison, relations, evolution, conflicts]
  RES[RIE for methods/datasets/benchmarks/metrics]
  GAP[Gap detection + overlap/contradiction probes]
  IDEA[Ideas, novelty search, red-team]
  RIG[RIE for gaps and ideas: novelty dimension]
  REPO[GitHub + Hugging Face resolution]
  RMOD[RIE for models and repositories]
  EXPP[Experiment plans + tracking]
  PROP[Reports, proposals, LaTeX/PDF export]
  MON[Monitoring + impact alerts]
  VM[Version Matcher: confidence-aware preprint/publication matching]
  DATE[Date Resolver: date claims, confidence, release types, UTC windows]
  LAT[Latest Research scans + page]
  RET[Evidence Retriever + Context Builder]
  ASK[Ask & Learn conversations + summaries with carried evidence + access-level boundaries]
  GW[LLM gateway: provider-independent, task config]
  SECS[Security scaffolding: project scope, localhost bind]
  MAN[Manifestations: preprint vs published]
  ANN[arXiv announcement capture job]
  GATEH[Gate H: hosted-deployment security]
  GR[Graph-ready model: UUIDs, row_version, relation metadata, research_relations, tombstones]
  GSV[GraphService + PostgreSQL implementation]
  NEO[R2: Neo4j + sync + reconciliation]
  GTRAV[R3: graph traversal for gaps, related work, novelty]
  GPROV[R4: proposal/experiment/result graph + provenance trails]
  GEVO[R5: continuously evolving graph]
  LES[Progressive lessons + project learning progress]
  RETN[Retention + deletion controls]

  F0 --> D1 --> D2 --> RA
  F0 --> OBJ --> RA
  RA --> RB --> CARD
  RA --> FM
  D2 --> FM
  D2 --> PDF --> EXPL
  CARD --> LP
  FM --> LP
  EXPL --> LP
  PDF --> EXT --> ENT --> RES
  EXT --> CMP
  PDF --> EQ --> EXPL
  ENT --> GAP
  CMP --> GAP --> IDEA --> RIG
  ENT --> REPO --> RMOD
  RES --> EXPP
  RMOD --> EXPP
  RIG --> EXPP --> PROP
  CMP --> PROP
  D1 --> DATE
  D2 --> MAN --> VM --> DATE --> LAT
  ANN --> DATE
  F0 --> GW --> OBJ
  F0 --> SECS --> GATEH
  RETN --> GATEH
  F0 --> GR --> GSV --> FM
  GSV --> NEO
  EXT --> NEO
  NEO --> GTRAV --> GAP
  GTRAV --> IDEA
  NEO --> GPROV --> PROP
  GPROV --> GEVO
  MON --> GEVO
  RB --> LAT
  CARD --> LAT
  PDF --> RET --> ASK
  EXPL --> ASK
  ASK --> LES --> LP
  ASK --> RETN
  EQ --> ASK
  EXT --> ASK
  LAT --> MON
  RIG --> MON
  D2 --> MON
```

The critical path to the MVP is
F0 (+ GW, SECS) → D1 → D2 → MAN → VM → DATE (+ ANN) → OBJ/RA → RB → CARD → LAT,
then (FM, PDF → RET → EXPL/ASK) → LES → LP. Gate H (security) is off the MVP
critical path but blocks any hosted deployment.
Latest Research depends on the Date Resolver and RIE, but not on full text.
Ask & Learn depends on the PDF pipeline and retrieval; it gains equations
(EQ) and multi-paper comparisons (EXT) in R2 without redesign.

## 3. Releases

| Release | Theme | Journey stages served |
|---|---|---|
| **R0** | Foundation | — |
| **R1 (MVP)** | Discover, Filter & Learn | DISCOVER, FILTER (papers), LEARN, UNDERSTAND (reading) · **Latest Research** · **Ask & Learn v1** |
| **R2** | Understand & Compare **+ Neo4j knowledge graph introduced** | UNDERSTAND (full), COMPARE, FILTER (methods/datasets/benchmarks/metrics); validated records synchronised to Neo4j |
| **R3** | Investigate & Validate | INVESTIGATE, VALIDATE; graph traversal for gap discovery, related work and novelty investigation |
| **R4** | Experiment & Propose | EXPERIMENT, PROPOSE; proposals, experiments, methods and results connected in the graph; provenance trails |
| **R5** | Persist & Monitor | all (long-term); scheduled Latest Research scans + notifications; continuously evolving knowledge graph |

### Why this MVP
- It delivers the critical new requirement (objective-aware usefulness with
  explanations and overrides) and the beginner positioning (primer, glossary,
  path, read-with-me).
- It builds the foundations every later release reuses: research record,
  provenance, RIE core, claims and verification, explanation service, PDF
  pipeline, events and journey registry.
- It works for experts too: a deduplicated, cited, objective-ranked collection
  with reasons, overrides and a field map.
- Its core runs on free sources. The LLM adds depth, but the MVP isn't
  useless without it.

- Latest Research and Ask & Learn are mostly reuse. Latest Research is the
  discovery workflow with date bounds plus the RIE. Ask & Learn replaces the
  earlier one-shot section explainer with a conversation on the same Tutor.
  Adding them to R1 costs one milestone, not a release.

R1 ships in four internal milestones so value appears early:
**M1a Discover** → **M1b Filter** → **M1c Latest Research** → **M1d Learn & Ask**.

### Implementation order (after approval)
1. **R0 Foundation:** two PRs (scaffold + DB/migrations + LLM gateway skeleton; API/worker/SSE/frontend shell/compose + security scaffolding). In parallel: assign evaluation roles (D19) and build B0.
2. **M1a Discover:** identifiers → SourceClient → clients (arXiv API + announcement feeds, S2, OpenAlex basic, Crossref, bioRxiv/medRxiv) → paper tables with manifestations + Version Matcher + G-MATCH → date events + provenance + Date Resolver (D28 revised) + announcement capture job + preprint labels + UTC/time-zone handling + G-LATEST-DATES → objective + Planner → discovery workflow.
3. **M1b Filter:** signals → scoring/tiers/anti-proxy → Stage B + cross-checks → cards + validator → overrides/feedback → triage UI.
4. **M1c Latest Research:** scan planner + W8 → abstract-mode extraction, relation_to_project, linker, Action Recommender → Latest brief + digest → page.
5. **M1d Learn & Ask:** field map → PDF pipeline → retrieval + context builder → Tutor answer mode + conversations + summaries → progressive teaching + progress → saved explanations → retention → glossary + learning path → read-with-me.
6. Evaluation: B0 from R0; B1 calibration splits during M1a–M1d; B3 held-out built by the custodian before the R1 release. Usability round. R1 release blockers (§8.1).
7. **Gate H** (security, §8.2) before any hosted deployment; independent of R2.

Within each milestone, the parts that work without an LLM are built and
tested before the LLM layer that enriches them.

## 4. Phase tasks and acceptance tests

Acceptance tests have IDs. "(E)" means the test is defined in
EVALUATION_FRAMEWORK.

### R0 — Foundation
**Tasks**
1. Monorepo scaffold: `backend/` (uv, Python 3.12, ruff, mypy, pytest), `frontend/` (Vite, React, TS, Tailwind, TanStack Query), pre-commit, `.env.example`.
2. Settings, structured logging with secret filtering, problem+json errors, health endpoints.
3. Postgres 16 + pgvector + pg_trgm; Alembic; tables: users, projects, research_items, research_runs, task_executions, run_events, checkpoints, domain_events, claims (+evidence, verifications).
4. Postgres job queue + worker; LangGraph Postgres checkpointer; SSE via LISTEN/NOTIFY.
5. Event outbox writer and dispatcher (idempotent consumers).
6. Journey registry with the nine stages (readiness stubs) and `GET /projects/{id}/journey`.
7. Frontend shell: layout, journey bar, dashboard, new-project form (topic, level, goal), run progress view.
8. Docker Compose (postgres, grobid, api, worker, frontend); CI (lint, types, tests, build, secret scanning).
9. **LLM gateway skeleton:** provider-neutral interface, task → {provider, model} configuration file marked provisional (D1), fake gateway, first provider adapter behind `llm/adapters/`, lint rule forbidding provider SDK imports elsewhere.
10. **Security scaffolding for later hosting** (cheap now, costly later): `project_members` with a single local owner, a `ProjectScope` dependency on every project route, repository methods that require a scope, localhost-only bind unless `AUTH_MODE` is set, private file storage served through the API.
11. **Graph-ready foundations:** UUIDv7 keys everywhere; `graph_nodes` identity registry and `node_source_registry` inventory (registration triggers only on listed node-source tables, with their conditions; node scope immutable); `row_version` trigger convention; `GraphService` interface with the PostgreSQL implementation skeleton and a backend-neutral `GraphView` schema; lint rule that the Neo4j driver may only be imported in `graph/adapters/neo4j/` (ARCHITECTURE §12).

**Acceptance tests**
- R0-1 `make up` from a clean clone starts all services with healthy checks.
- R0-2 `/health/ready` returns 200 only when Postgres is reachable; otherwise problem+json 503.
- R0-3 A dummy workflow streams events to the UI, pauses at a checkpoint, survives a worker restart and resumes after approval.
- R0-4 An event written in a rolled-back transaction is never dispatched; a consumer that fails is retried and is idempotent.
- R0-5 Logs never contain configured secret values (test).
- R0-6 Migrations upgrade from empty and downgrade cleanly.
- R0-7 Journey endpoint returns nine stages with deterministic states for a fixture project.
- R0-8 **Provider independence:** swapping the task configuration to the fake provider runs the dummy workflow unchanged; the lint rule fails the build if a provider SDK is imported outside `llm/adapters/`; run manifests record provider, model and `provisional = true`.
- R0-9 Every project-scoped route rejects requests without a resolved project scope (route-inventory test); the server refuses to bind to a non-local address with authentication disabled.
- R0-10 **Graph readiness:** a migration test asserts that (a) exactly the tables in `node_source_registry` have a registration trigger (and `experiment_plans`, glossary terms and non-proposal reports do not), each with a UUID key and a working `row_version` trigger; (b) registration respects the conditions (a discovery report or a `term` entity creates no `graph_nodes` row; a proposal report does); (c) a node's `scope_project_id` equals its source row's project and cannot be updated; (d) `GraphService` (PostgreSQL) returns a `GraphView` for a fixture project; (e) the lint rule rejects a Neo4j import outside the adapter.

### R1 — MVP: Discover, Filter & Learn (+ Latest Research, Ask & Learn)

**M1a Discover — tasks**
1. Identifier parsing/normalisation (DOI, arXiv old/new, S2, OpenAlex) with property tests.
2. `SourceClient` base: rate limits, retries, circuit breaker, HTTP cache, source records, usage budgets.
3. Clients: arXiv (API + daily announcement feeds), Semantic Scholar, OpenAlex (basic access, budgeted; `OPENALEX_CAPABILITIES` switch with both paths tested, D24), Crossref (incl. `relation`, `posted`, `accepted` fields), bioRxiv/medRxiv (`/details`, `/pubs`; D22); each client records reporting source and any exposed upstream provenance; integration docs with verified-on dates (including the arXiv feed field semantics).
4. Paper tables with **manifestations** (`paper_manifestations`; identifiers, dates, documents and evidence per manifestation), dedup (identifier union-find), **Version Matcher** with `paper_match_decisions` (decisive / strong / supporting / contradicting evidence; possible matches linked, not merged; reversible; D29), enrichment, citations, survey detection. G-MATCH B0 + B1 splits before tuning thresholds.
4a. Date provenance: `paper_dates` as separate **events** (submitted, announced/posted, revised, accepted, published online, issue, issued, reported, indexed, metadata) with reporting source and upstream provenance; Date Resolver (system-of-record lookups; confidence verified / corroborated / source agreement / single source / conflicting / uncertain — D28 revised; first public appearance + basis incl. `submission_only`; release-type rules incl. "journal version is not new research"); **arXiv Announcement Capture** daily job and `arxiv_announcement_log`; preprint labelling; UTC storage and windows with boundary-day flags (D23); user time zone and `LocalTime` display; table-driven tests from G-LATEST-DATES (B0, B1 splits).
5. Research objective model + Planner (LLM) + rule-based fallback; objective editor UI.
6. Discovery workflow W1 with plain-language checkpoints; search log; manual add by identifier.

6a. **Graph-compatible relationships:** common relationship columns (assertion, confidence, evidence, provenance, scope, status, row_version) and evidence-by-assertion constraints on all relationship tables; `research_relations` (six types only), `structural_relations` (PART_OF and RESULT_FOR only; composite FKs to `graph_nodes`), `relation_registry` and `relation_endpoint_rules` (endpoint, cardinality and delete rules), `enforce_relation_scope()` on every source registered in `relation_registry` (structural sources included, e.g. `paper_manifestations` for HAS_VERSION), driven by the registry's endpoint/scope columns and scope policy, `relation_decisions` (project-scoped overlays for decisions on global relationships), `entity_links` (replacing `paper_entity_mentions`), `relation_assertion_log`, `relation_suppressions`, `research_groups`, `author_affiliations`, `entity_tombstones` (minimum metadata, 30-day cap); `RelationWriter` as the single write path with sticky rejection; relation registry mapping every relationship type to exactly one PostgreSQL source; R1 graph capabilities (citation graph, versions, 1-hop neighbours, basic related papers) served by `GraphService` (PostgreSQL); graph parity fixture set prepared for R2.

**M1b Filter — tasks**
7. Signal plugin framework; Stage A paper signals (semantic match, focus/exclusion coverage, in-corpus citation share, co-citation, intents, field-normalised citations with cap, survey flag, currency).
8. Scoring, objective profiles, tiers, role tags, anti-proxy rules; assessment history; staleness via events.
9. Stage B: Relevance Judge with verified quotes; cross-check runner; top-K control; budget accounting (`llm_usage`).
10. Card skeleton builder + Card Writer + ClaimValidator; card cache; "How was this ranked?".
11. Overrides, feedback, decision log, objective suggestions, bounded weight adaptation.
12. Filter/Triage UI with beginner and advanced views; seed selection for citation expansion uses Stage A priority.

**M1c Latest Research — tasks**
12a. Planner `LatestScanPlan` (per-subtopic queries, arXiv category mapping, bioRxiv/medRxiv category mapping for life-science objectives) and the Latest Scan Planner service; date-bounded source queries (arXiv `submittedDate` + category sweep; bioRxiv/medRxiv `/details` + `/pubs`; S2 date-range search; OpenAlex publication-date filter, plus created-date filter only when the premium capability is enabled; Crossref `from-pub-date` and DOI date confirmation).
12b. W8 Latest scan workflow; `latest_scans`, `latest_scan_entries`, `latest_views`; coverage and failure recording; refresh on open if older than 24 h.
12c. Relevance Judge `relation_to_project` (challenges cross-checked); Extractor abstract mode (incl. comparative statements and author-stated limitations/future work); Related Item Linker (cites vs similar); Action Recommender; Card Writer **Latest brief** (eight questions), "What's new" and digest mode.
12d. Latest Research page: window picker (local-time display), release-type tabs, eight-question briefs (beginner/advanced views), action chips with override, filters (incl. action), date provenance popover, possible-match prompts, entry actions (save, dismiss, read later, notes, Ask about this), "new since last visit".
12e. G-LATEST-DATES and G-LATEST-RELEVANCE (first 5 topics × 2 weeks of frozen responses).

**M1d Learn & Ask — tasks**
13. Field Mapper (embeddings + citation communities, keyword labels, optional LLM labels) and field map UI.
14. PDF pipeline: resolver chain (arXiv, S2 OA, OpenAlex OA, Unpaywall, upload), downloader, GROBID sections, chunks + embeddings; precise failure reasons.
15. Explanation service (on-demand, cached, streamed) + Tutor: primer, glossary definitions, section explanations; grounded/background labelling; level switch.
15a. Evidence Retriever (hybrid pgvector + full-text, scoped) and Context Builder (project + view context + memory within budget).
15b. Ask & Learn: `tutor_conversations`, `tutor_messages`, `tutor_message_evidence`, `conversation_summaries` (summary text + deterministically collected `carried_refs`); Scope Router; Tutor answer mode with seven styles and follow-up intents; `TutorAnswer` validation (grounding, not-found, equation rule, background restrictions, **no summary/assistant-message evidence**); saved explanations (independent copies); feedback; prerequisite offers → Curriculum Builder.
15b-2. **Progressive teaching:** `teaching_sessions`, `understanding_checks`, `concept_progress`; Tutor teaching mode (eight steps, lazy generation, skip reasons, simpler/deeper/jump, interrupt and resume); check grading; Learning Progress Tracker; progress on the Learn page and learning path.
15b-3. **Retention:** project retention policy, delete conversation / delete all / reset progress, Retention Enforcer daily job, cascade rules.
15c. Ask & Learn panel available on every page (context chips, scope switch, follow-up chips, sources, lesson stepper and controls); text selection → Ask; history, saved explanations and learning progress page; retention settings.
16. Term Miner + glossary UI with "appears in" links.
17. Curriculum Builder + learning path UI with progress.
18. Read-with-me UI (paper + Ask & Learn side by side); reading status, notes, saved items, project history.
19. Discovery report (Markdown) and BibTeX/CSV export.
20. Evaluation harness, G-TOPICS, G-DEDUP, G-RELEVANCE (first 5 topics), G-EXPLAIN (R1 subset), G-TUTOR (R1 subset: a, b, d, e, f, g); usability round including both new features.

**Acceptance tests**
- R1-1 End-to-end run in fixture mode and live mode for 5 reference topics, from the three-field start to filtered collection, primer and learning path.
- R1-2 One canonical paper when the same work arrives from arXiv, S2 and OpenAlex; dedup precision/recall targets met (E §3.1).
- R1-3 Every query, source response, failure and cache hit is recorded; the run is replayable from cache with the same item set.
- R1-4 Rate-limit tests: arXiv ≤ 1 req/3 s; `Retry-After` honoured; a failing source is marked degraded and the run ends `partially_succeeded` with a coverage notice.
- R1-5 With no LLM key: discovery, Stage A tiers (capped at Recommended), card skeletons, field map with keyword labels, glossary term list and reading UI all work; LLM-only features show a clear "not available" message.
- R1-6 **Anti-proxy:** property test — items with only citation and date signals never reach Essential or Recommended; changing content signals with fixed citations changes ranking.
- R1-7 **Beat-the-proxy (E §3.2):** RIE nDCG@20 exceeds citation-only, recency-only and similarity-only rankings on every held-out topic.
- R1-8 Essential precision ≥ 0.85 and Not-useful precision ≥ 0.90 on the B3 held-out benchmark (E §2a).
- R1-9 Every card has all six fields (or an explicit "none found" plus a missing-info entry); every Reported/Extracted statement verifies; every grounded AI statement references valid evidence.
- R1-10 High-stakes judgements are cross-checked; a disagreement produces an "uncertain" label and lower confidence (fixture test).
- R1-11 Overrides persist across recomputes; a later system change produces a non-blocking notice; overrides appear in the decision log and exports.
- R1-12 After 20 fixture overrides, weight adaptation stays within ±50% of defaults, is shown to the user and can be undone; no change happens before the threshold.
- R1-13 "Wrong" feedback hides the statement immediately and creates a review record.
- R1-14 Second request for the same (subject, level) explanation is served from cache with no LLM call; sections never opened are never explained.
- R1-15 Background explanations containing paper names, citations or results not in the project are rejected (adversarial suite).
- R1-16 Unavailable full text shows a one-sentence reason and an upload option; the explanation is labelled "Based on the abstract only".
- R1-17 Field map: 3–8 directions per reference topic, each ≥ 3 papers, with basis recorded; deterministic with fixed seeds.
- R1-18 Glossary ≥ 15 terms per topic, each linked to ≥ 1 verified span; learning path never violates recorded prerequisites.
- R1-19 Default screens pass the banned-jargon scan; progress messages within 2 s and every ≤ 10 s.
- R1-20 Honesty gates (E §3.3) pass with zero tolerance.
- R1-21 Usability: ≥ 4 of 5 beginners complete the journey without help and pass the comprehension check; 3 experts review their own topic, and any fabrication is release-blocking.
- R1-22 Playwright e2e: create → confirm objective → review set → open card → override → read primer → open path paper → explain a section at two levels → find it in history.

*Latest Research*
- R1-23 Default window is the rolling 7 days; changing the range re-queries or re-filters correctly; window boundaries (exact start/end, UTC vs. displayed timezone) pass (E §3.8).
- R1-24 Release-type classification passes every G-LATEST-DATES case: revisions never appear as new preprints; metadata-only changes never appear as new; journal versions of earlier preprints are labelled with the preprint date; month/year-precision and conflicting dates go to *Date uncertain*.
- R1-25 Automated audit: every displayed date equals a stored source-record value of the stated type and source, and shows its retrieval timestamp; 0 violations.
- R1-26 The same work from arXiv, S2, OpenAlex and Crossref appears once; a recent paper already in the project shows its existing state (saved, notes, overrides).
- R1-27 Recall ≥ 0.90 (arXiv-covered fields) and default-order nDCG@10 ≥ 0.70 on G-LATEST-RELEVANCE; shuffling dates within the window doesn't change "Read first" order.
- R1-28 Contribution, method and dataset statements verify against the abstract or say "Not stated in the abstract"; "cites" links are backed by citation records, and "similar" links are labelled.
- R1-29 A failed or rate-limited source shows in the coverage line, and the scan completes as partial; an empty window shows an explanation and a wider-window suggestion.
- R1-30 Save, dismiss (with reason), read later and notes from Latest Research appear consistently on Papers, Filter and History; "new since last visit" counts are correct across visits.
- R1-31 A scan is reproducible from stored responses: same window, same objective version → same entries and release types.

*Ask & Learn*
- R1-32 Scripted multi-turn dialogues keep context: references to earlier turns, anchor retention and scope switches (≥ 0.9, E §3.9).
- R1-33 Anchored question test: "What is message passing?" while viewing a GNN fixture paper answers with the paper's meaning first and cites its section/page; the same question in General scope gives a labelled background answer.
- R1-34 Unanswerable-from-paper questions return "Not found in the available text" before any background, with no paper-attributed claims (≥ 0.95; 0 fabricated claims).
- R1-35 Validator rejects paper-attributed equations not matching an extracted equation or user selection, unverifiable quotes and background blocks naming papers or results not in the project (adversarial suite).
- R1-36 Each style and follow-up intent produces the requested form (rater check ≥ 0.9); code blocks are labelled "not run".
- R1-37 Level fit and accuracy targets met on G-TUTOR R1 subset (E §3.9).
- R1-38 Saving an answer creates a **saved explanation** that keeps its sources and claim kinds; deleting the conversation leaves the saved explanation intact (its link to the source message becomes empty).
- R1-39 Prerequisite offers map to glossary/concept items; "Build a learning sequence" adds ordered items to the learning path without violating recorded prerequisites.
- R1-40 Ask & Learn opens from paper reading, cards, Latest Research, glossary, learning path and field map with the correct context chips; time to first token p50 ≤ 3 s.
- R1-41 Canonical asks (same subject, level, style, no prior turns) are served from cache with no LLM call.

*Final-review additions (dates, matching, teaching, memory)*
- R1-42 **Secondary-source-only dates:** a paper whose only day-precision date is from OpenAlex (or only Semantic Scholar) is `single_source` → *Date uncertain*, shown as "unconfirmed", never in *New research*; when the system of record later supplies a date it is reclassified with a "Reclassified" badge.
- R1-43 **Conflicting publication dates:** primary events more than 2 days apart → *Date uncertain* with all events and sources listed; a secondary claim disagreeing with a primary event is flagged in provenance, and the primary date stands.
- R1-44 **Preprint-to-journal matching:** arXiv and bioRxiv/medRxiv preprints with Crossref `relation`, bioRxiv `/pubs` or arXiv `doi` links are auto-matched; the journal version is classified "Published version of an earlier preprint" with the preprint date shown; G-MATCH precision/recall targets met (E §3.1).
- R1-45 **Similar-title false matches:** none of the G-MATCH adversarial pairs (different authors, Part I/II, comment/reply/erratum, conference vs extended version, thesis vs article) is merged; a property test confirms title similarity alone never produces a match; possible matches are linked, not merged, until the user confirms.
- R1-46 **Match preservation:** after a merge, every original source record, identifier and date claim (with manifestation) is still present; splitting restores both papers exactly; user confirm/reject decisions survive re-matching.
- R1-47 **Local time-zone display:** with the user zone set to Europe/Berlin, America/Los_Angeles, Asia/Kolkata and Pacific/Kiritimati, timestamps and window bounds display correctly (incl. DST transitions); date-only values display the same calendar date in every zone; changing the zone never changes which papers are in the window.
- R1-48 **Seven-day window boundaries:** with a fixed clock, a timestamp exactly at `now − 168 h` is included, one second earlier is excluded, `now` itself is excluded; date-only values on the start or end day are included and flagged `boundary_day`; month-precision values are never included.
- R1-49 **Latest brief:** every relevant entry has all eight answers, each evidence-backed or an explicit "can't tell / not stated / none stated"; opportunities cite an author-stated sentence; `challenges` relations are cross-checked; changing only dates or citation counts never changes the action (property test).
- R1-50 **bioRxiv/medRxiv:** enabled automatically for life-science objectives and toggleable per project; v1 posting dates classify New preprints; later versions classify as Revised; bioRxiv and medRxiv entries show "Preprint — not peer-reviewed" unless a matched journal manifestation is displayed.
- R1-51 **OpenAlex capabilities:** with the default `basic` capability, no premium filter is ever requested (asserted on the HTTP mock); with `premium_filters` enabled, created-date detection is used; both paths produce the documented "newly indexed" behaviour.
- R1-52 **Progressive teaching:** a lesson presents steps in order; a beginner starts at Intuition, an expert at Technical; "Simpler", "Go deeper", "Skip to" and "Stop" work; a mid-lesson question is answered and "Resume lesson" returns to the same step; inapplicable steps are skipped with a reason; check results update `concept_progress`; rubric targets met on G-TUTOR (h).
- R1-53 **Multi-turn tutor context:** in 25-turn scripted dialogues, questions that depend on turns 1–10 are answered correctly after summarisation (≥ 0.9), and pronoun and anchor references resolve.
- R1-54 **Project memory after summarisation:** after older turns are summarised, the objective, notes, saved explanations, concept progress and learning path are still loaded into context and unchanged; the summary is never cited as a source.
- R1-55 **Conversation deletion and retention:** deleting a conversation removes its messages, evidence links, summaries and conversation-only claims, and keeps saved explanations, concept progress and check results; "delete all" does the same project-wide; "delete after N days" expires conversations via the daily job (fixed clock); "don't keep history" stores no messages after the session; "reset learning progress" is separate and requires confirmation.
- R1-56 **Evidence preservation:** after summarisation and after the user saves an explanation, every evidence reference (span, chunk, equation, item) from the original turns still resolves to the same quote, page and section; the validator rejects citations of summaries or earlier assistant messages (adversarial suite).

*Architecture-review additions (provenance, manifestations, provider, tutor boundaries, evaluation)*
- R1-57 **Source agreement vs corroboration:** OpenAlex and Semantic Scholar agreeing on a date with unknown upstream provenance → `source_agreement` → *Date uncertain*, with "may share upstream data"; a fixture with recorded, disjoint upstream provenance → `corroborated`; the database trigger rejects `corroborated` without that evidence.
- R1-58 **Date events kept separately:** a fixture work with arXiv v1 submission, arXiv announcement, v2 revision, journal acceptance, online publication, issue publication and metadata updates stores and displays eight distinct events with their manifestations; the first public appearance is the announcement; metadata events never qualify.
- R1-59 **Submission-only arXiv dates:** without a captured announcement, the UI says "Submitted to arXiv … — public announcement date not verified"; with a captured announcement, the basis upgrades to `announced` and the wording changes; the 3-day fetch overlap never changes an entry's date or basis (test with the overlap disabled and enabled).
- R1-60 **Journal version of an existing preprint:** appears only under *Updates* with the preprint's first public date; it is excluded from "new research" counts and the digest's new-work section; its assessment is the existing work's (no novelty credit); a saved preprint's state carries over.
- R1-61 **Preprint labels and manifestations:** bioRxiv, medRxiv and arXiv manifestations show "Preprint — not peer-reviewed"; a matched journal manifestation is shown as a distinct "Journal version" line; evidence quotes state which manifestation they come from; splitting a match restores both manifestations intact.
- R1-62 **Tutor capability boundaries:** for fixtures at each access level, abstract-only papers produce "Based on the abstract only" and "Not available in the extracted text" for beyond-abstract questions; full-text answers cite sections/pages only when the text was processed; paper-equation explanations occur only for equation text that is available (verified selection in R1); garbled selections produce "can't read this equation reliably"; general concept questions are answered and labelled background.
- R1-63 **Evaluation data separation:** an automated check confirms no item hash appears in more than one of B0/B1/B3 or in prompt examples; B3 runs are executed by the custodian; the R1 evaluation report states CI intervals and the approver.
- R1-64 **Relationship metadata:** every relationship row produced in R1 (citations, authorship, affiliations, term mentions, related-item links, relevance relations, match links) has an assertion, provenance and scope; LLM-produced relationships are stored as `inferred` with evidence and confidence; none is ever shown as established without verification or user confirmation (UI and API label check).
- R1-65 **One source per relationship type** (schema and registry test suite):
  (a) `relation_registry` has exactly one row per type (all research types, IMPLEMENTED_BY from R4, and the structural types HAS_VERSION, IN_PROJECT, PART_OF, RESULT_FOR), and the code registry matches it;
  (b) `research_relations` rejects types outside its six, and `structural_relations` rejects anything but PART_OF and RESULT_FOR (CHECK constraints);
  (c) **FK allow-list:** every reference column between node-source tables is either a registered relationship source or a declared non-source (scope, derived pointer, node data, derived analytics, learning data, decision log, snapshot, project memory); an undeclared column fails the build;
  (d) tables that aren't node sources reference only their owning node and relationship `uid`s (e.g. `experimental_protocols`), except in the declared categories;
  (e) declared non-sources (`direction_relations`, `taxonomy_nodes`, `concept_prerequisites`, snapshots) produce no graph edges in the projector (asserted on fixtures);
  (f) **endpoint integrity:** inserting a relationship to a missing node, a node of the wrong kind, or a disallowed `(type, from_kind, to_kind, role)` is rejected by the database;
  (g) **cardinality and deletion:** a sub-question without exactly one PART_OF → Objective, or a paper-reported result without exactly one `reported_in` paper and one metric, fails at commit; deleting an objective cascades to its sub-questions; deleting a proposal detaches its experiments; every deleted link writes a deletion marker;
  (h) structural relationships always carry `assertion = structural`, have no evidence, cannot be rejected, and are never counted or displayed as findings.
  (i) **cross-project rejection:** a relationship whose endpoints belong to project P and project Q is rejected by the database for every relationship table and type (two-project fixture), including via direct SQL that bypasses `RelationWriter`;
  (j) a relationship scoped to Q that touches a P node, or a P-scoped relationship between a Q node and a global node, is rejected;
  (k) a global (`null`-scope) relationship touching any project-scoped node is rejected; a global relationship whose provenance shows project context, or whose assertion is a user assertion, is rejected;
  (l) a relationship between a global node and a P node with scope P is accepted; a relationship between two global nodes is accepted with scope null (global inputs only) or scope P;
  (m) **registry-driven enforcement check:** for every `relation_registry` row (research and structural types, including HAS_VERSION, IN_PROJECT, PART_OF and RESULT_FOR), CI verifies in the live schema that the source table has `enforce_relation_scope()` attached, that the declared endpoint and scope columns exist with their foreign keys, that `CHECK (scope_project_id IS NULL)` exists where the policy is `global_only` and a scope column exists, and that a source without a scope column has policy `global_only`; a registry row added without enforcement fails the build (tested by a fixture that registers a dummy type without the trigger);
  (n) **decisions on global relationships:** a user in P rejecting or confirming a global relationship creates a P-scoped `relation_decisions` overlay (plus a suppression for rejections); the global row is unchanged; a user in Q still sees the relationship unchanged;
  (o) a node's scope cannot be changed after registration; deleting project P removes all P-scoped relationships, including those between global nodes, and writes deletion markers.
  (p) **HAS_VERSION scope:** attempts to link a `paper_manifestations` row to, or from, a project-scoped node (via a crafted `graph_nodes` fixture or direct SQL) are rejected by the database; HAS_VERSION has no scope column and its registry policy is `global_only`; the projector emits HAS_VERSION edges only with global scope, and the scope audit (R2-16) finds none with a project scope.
- R1-66 **Tombstones:** deleting a conversation, project or merged paper writes `entity_tombstones` for every affected graph uid (no content), even though Neo4j is not yet deployed.
- R1-67 **Rejected relationships stay rejected:** after a user rejects an inferred relationship, (a) re-running the same extraction or judgement, (b) a near-duplicate with different wording (suppression fingerprint), (c) resync, reconciliation and full rebuild (R2 fixtures) never re-create or re-activate it; only a user action can change it; each suppressed attempt is logged.
- R1-68 **Evidence by assertion:** inserts violating the evidence rules (e.g. `extracted` without a verified span, `inferred` without confidence or evidence, `source_metadata` without a source record) are rejected by the database; `structural` rows carry no evidence.
- R1-69 **Deletion markers:** markers contain only uid, kind, reason and timestamps (schema test: no content, endpoint, project or user columns); conversation, project and account deletions and retention expiry write markers for every affected project-scoped graph element; markers are purged after verified absence or at the 30-day cap (with an alert if unverified); `deletion_log` stores only hashes and counts.

### R2 — Understand & Compare
**Results storage:** paper-reported results write their paper, method, dataset/benchmark and metric only as `RESULT_FOR` rows in `structural_relations` (read through `result_dimensions_v`); experimental protocols reference `entity_links` rows.
**Knowledge graph tasks:** add the `neo4j` service — behind a Compose profile during R2 development, and a **required service in the default deployment from the R2 release** (health check reports `graph: degraded` if it is missing); uniqueness constraints on `uid` per label; Graph Projector + Graph Sync Worker (outbox-driven, version-guarded MERGE, retries, dead letters, tombstones); Graph Reconciler (daily count/hash comparison, repair, orphan deletion) and blue/green full rebuild; `Neo4jGraphService` with named Cypher templates; backend switch with PostgreSQL fallback; parity test suite; sync **validated** records only (established assertions); move citation graph, field map, evolution and comparison neighbourhoods to the graph where beneficial; graph monitoring (sync lag, dead letters).
**Tasks:** Ask & Learn gains paper equations (from arXiv LaTeX) with step-by-step maths, algorithm/architecture walkthroughs with pseudocode, and multi-paper questions grounded in extractions; Latest Research cards gain full-text-verified contributions/datasets for open-access recent papers; Extractor (contributions, methods, datasets, metrics, results, limitations, assumptions, protocols, compute) with quote verification and Batches API option; typed entity normalisation + detail tables; arXiv LaTeX source + equation explainer; algorithm explainer; exercises (not run); Comparator (tables, EXTENDS/CONTRADICTS/RELATED_TO rows in `research_relations`, evolution, conflicts with comparability); field map v2 (methods/datasets per direction, taxonomy); RIE signals for papers using full text, plus RIE for methods, datasets, benchmarks and metrics; resources UI; G-EXTRACT and G-RESOURCES evaluation.

**Acceptance tests**
- R2-1 Extraction targets met on G-EXTRACT (E §3.6); 100% of persisted extractions have verified evidence.
- R2-2 Every `reported_results.value_text` appears inside its evidence quote.
- R2-3 Equation explanations quote the paper's symbol definitions when present and label inferred ones; non-arXiv equations come only from user selection.
- R2-4 Comparison cells link to evidence or show "not reported"; conflicts show a comparability check (split, setting, backbone).
- R2-5 Dataset and metric cards show licence and access only from metadata (never LLM-inferred); a missing licence appears in missing information.
- R2-6 Dimension agreement κ ≥ 0.6 with full text (E §3.2); paper tiers re-evaluated after extraction, with tier changes notified.
- R2-7 Exercises always display "not run".
- R2-8 Mathematical explanation targets met on G-TUTOR (c) (E §3.9); paper equations in answers match extracted LaTeX exactly.
- R2-9 **Idempotent sync:** replaying the full event log twice, and in shuffled order, produces an identical graph (node/edge sets and properties); stale events (lower `pg_version`) never overwrite newer state.
- R2-10 **Stable identity:** a full rebuild from PostgreSQL produces the same node and edge `uid`s as incremental sync.
- R2-11 **Retries and dead letters:** with Neo4j stopped during writes, PostgreSQL writes succeed; after restart, pending items sync; items failing N times appear in dead letters and are repaired by reconciliation.
- R2-12 **Reconciliation:** injected drift (missing nodes, extra orphans, stale versions) is detected and repaired; the run is logged in `graph_sync_runs`.
- R2-13 **Deletion propagation:** user deletions, retention expiry, project and account deletion, rejections and merge splits remove the corresponding nodes and edges from Neo4j (marker audit), including project-scoped inferred edges; markers pending during a full rebuild are applied before switch-over; the orphan sweep removes anything without an eligible PostgreSQL row.
- R2-14 **Validated records only:** possible matches, unverified extractions, hidden claims, rejected relations and (in R2) inferred/hypothesised relationships never appear in Neo4j.
- R2-15 **Backend parity and independence:** the parity suite returns identical `GraphView` results from the PostgreSQL and Neo4j implementations for the **R1 capability set** (citation graph, versions, 1-hop neighbours, basic related papers); switching the backend changes no API response schema.
- R2-16 **Scope isolation in the graph:** a project member cannot retrieve another project's scoped nodes or edges through any `GraphService` method (automated suite); no edge is returned unless both endpoints are visible in the caller's scope; P's overlays never affect Q's results; cross-project queries return only global nodes; the projector refuses rows violating the scope invariant (with an alert); reconciliation's scope audit reports 0 violations in Neo4j.
- R2-17 **Capabilities and degraded mode:** R2-only capabilities (multi-hop paths, rich exploration) return `graph-capability-unavailable` from the PostgreSQL backend, never approximated results; with Neo4j stopped, health reports `graph: degraded`, R1 capabilities keep working via PostgreSQL, and graph-only features show the unavailable message.

### R3 — Investigate & Validate
**Knowledge graph tasks:** named traversal patterns for gap discovery (method × dataset structural holes, limitations along `EXTENDS` chains, weakly connected directions), related-work analysis (multi-hop `CITES`/`EXTENDS`/`USES_METHOD` with assertion policies) and novelty investigation (hypothesis neighbourhood, `CONTRADICTS` paths); `graph_query_log` for reproducibility; sync of `inferred`/`hypothesized` relationships with labels; user confirm/reject of inferred relationships.
**Tasks:** limitation clustering (independent-group rule), intersection matrices, conflict-derived gaps; Novelty Search service; overlap and contradiction probes; Gap Investigator; RIE for gaps; hypotheses with falsification criteria; Red-Team Reviewer with revise loop; RIE for ideas (novelty dimension) and novelty-implication signals on papers; idea status tracking; gap and idea UIs; G-GAPS evaluation.

**Acceptance tests**
- R3-1 Every gap stores reproducible signals and has both an overlap probe and a contradiction probe with recorded queries.
- R3-2 The gap view shows evidence for and against side by side; "already addressed" links the addressing work with a quote.
- R3-3 Every idea links to its gap, evidence for and against, a novelty check (queries, sources, date, nearest work) and ≥ 1 red-team review.
- R3-4 No output contains banned novelty phrasings (automated scan).
- R3-5 Papers gain "closest prior work / supports / challenges" novelty tags against user ideas, with quotes.
- R3-6 Gap reality and probe adequacy targets met (E §3.7).
- R3-7 Idea status changes are logged with reasons.
- R3-8 **Graph-derived signals are reproducible:** each gap or novelty signal derived from the graph records template, parameters, assertion policy and `graph_version`; re-running against the same graph version gives the same result.
- R3-9 **Inferred never treated as established:** with the default policy, traversals exclude inferred and hypothesised edges; with `include_inferred`, every path reports its weakest assertion and derived statements are labelled AI interpretation or hypothesis (fixture with a mixed path).
- R3-10 **Graph adds value:** on B1/B3 gap and novelty sets, the graph-assisted pipeline finds at least as many expert-confirmed gaps and at least as much known prior work as the non-graph pipeline (no regression), with improvement reported.
- R3-11 Confirming or rejecting an inferred relationship updates PostgreSQL, logs the change, and reaches Neo4j through sync; rejected relationships are never re-proposed.

### R4 — Experiment & Propose
**Experiments storage:** experiment → proposal (`PART_OF`, detach) and user result → experiment (`PART_OF`, cascade) and result dimensions (`RESULT_FOR`) live only in `structural_relations`.
**Knowledge graph tasks:** `Proposal`, `Experiment`, `Result`, `Repository` and `Model` nodes; `DERIVED_FROM`, `ADDRESSES`, `VALIDATED_BY`, `USES_METHOD`, `EVALUATES_ON` connections; provenance-trail queries and UI (proposal → hypothesis → gap → limitations → papers → evidence).
**Tasks:** GitHub and Hugging Face resolution with link confidence; RIE for models and repositories (constraint-aware: licence, size vs. compute, activity); experiment plans (datasets, baselines, metrics, protocols, ablations, compute from `compute_reports` only); experiment tracking with user-reported results; Writer; literature review and proposal reports; Citation Validator; LaTeX/PDF/BibTeX/RIS export.

**Acceptance tests**
- R4-1 Code links show link source and confidence; name-search-only matches are labelled "possible".
- R4-2 Compute estimates appear only when backed by `compute_reports`; otherwise "insufficient information".
- R4-3 Ablation suggestions are labelled AI interpretation and reference named method components.
- R4-4 User-reported results are never shown alongside paper-reported results without a distinguishing label.
- R4-5 100% of report citations resolve to project papers; factual sentences without citations are blocked or removed.
- R4-6 LaTeX export compiles in CI; references include DOI / arXiv ID / URL where known.
- R4-7 **Provenance trail:** for every proposal, the trail reaches quoted evidence for each cited gap and limitation; any link in the trail that is inferred is labelled as such.
- R4-8 User-reported results connect to hypotheses via `VALIDATED_BY` with outcome and `user_asserted` assertion, never mixed with paper-reported results.

### R5 — Persist & Monitor
**Knowledge graph tasks:** continuous incremental updates from monitors; temporal properties (`first_seen`, `valid_from`, `retracted_at`) and `graph_version` history; impact alerts by traversal (new paper → `ADDRESSES`/`CONTRADICTS`/`EXTENDS` → accepted hypotheses, open gaps, experiments); retraction handling; cross-project discovery on the global layer only; optional Graph Data Science analytics (D35).
**Tasks:** scheduled Latest Research scans per project (reusing W8) with notifications (in-app first, email optional); scheduled monitors; impact detection against open gaps, accepted ideas and running experiments; incremental re-assessment; multi-user collaboration features beyond gate H (shared projects, comments); optional sandboxed exercise execution; optional Qdrant adapter and optional additional graph infrastructure (e.g. read replicas, Graph Data Science analytics, D35) if scale requires it (Neo4j itself is already required since R2); backups and runbook.

**Acceptance tests**
- R5-1 Monitors are idempotent and notify only on new canonical papers.
- R5-2 Every impact alert contains the new paper, the affected item and the overlapping passage; dismissals are logged.
- R5-3 Re-assessment after new papers reuses prior signals and reports which tiers changed.
- R5-4 Scheduled scans produce the same entries as a manual scan for the same window; notifications are sent only for new Essential/Recommended entries or overlap/challenge flags, never for reclassified old papers.
- R5-5 **Evolving graph:** after a week of scheduled scans, new nodes and edges appear incrementally with correct `first_seen`; retracted relationships are marked, not silently removed from history; reconciliation stays clean.
- R5-6 **Impact by traversal:** fixture paths (new paper `CONTRADICTS` a paper that an accepted hypothesis `DERIVED_FROM`) raise an alert with the full path and evidence; paths through inferred edges are labelled.

## 5. Free-source plan

| Built first with free sources only | Needs an LLM (paid API or local model) |
|---|---|
| Discovery from arXiv, Semantic Scholar (free key), Crossref, Unpaywall; OpenAlex within its free allowance (optional) | Planner drafting objectives and queries (a form is the fallback) |
| Dedup, enrichment, citation graph, survey detection | Relevance judgements (Stage B) |
| RIE Stage A: deterministic signals, tiers (capped), role tags, missing information | Card prose, primer, definitions, explanations |
| Card skeletons (extracted statements, signals, missing information) | Curriculum ordering beyond role-based ordering |
| Field map with keyword labels | Extraction, comparisons, gaps, ideas, red-team, proposals |
| PDF retrieval, GROBID sections, read-with-me (without explanations) | Equation and algorithm explanations, exercises |
| Glossary term list with "appears in" links | |
| Latest Research: date-verified entries, release types, dedup, Stage A tiers, cites/similar links, filters, actions | Latest Research relevance reasons, contributions, overlap/challenge flags, digest |
| Ask & Learn passage search ("where does this term appear?"); saved explanations and learning-progress views; retention controls; version matching from identifier links | Ask & Learn answers, progressive lessons and checks; Latest briefs |
| Overrides, notes, decisions, history, exports | |
| GitHub and Hugging Face metadata (R4) | |

Order of work inside R1 follows this split: every free capability is built
before the LLM layer that enriches it.

## 6. Main technical risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| T1 | RIE rankings not better than simple proxies | Medium | High (core promise) | Beat-the-proxy release gate; gold sets before tuning; signals visible for debugging |
| T2 | LLM judgements or explanations wrong but plausible | High | High | Verified quotes, cross-checks, claim kinds, background restrictions, feedback hiding, human evaluation gates |
| T3 | Gold-set annotation effort underestimated | High | Medium | Start with 5 topics; recruit domain volunteers early; write guidelines first |
| T4 | API access changes (OpenAlex pricing, S2 limits) | Medium | Medium | Optional sources, budgets, cache, per-source coverage reporting |
| T5 | Low full-text availability outside CS/physics | High | Medium | Abstract-only mode clearly labelled; uploads; Unpaywall |
| T6 | LLM cost per project higher than estimated | Medium | Medium | `llm_usage` tracking from day one; top-K limits; on-demand cards; caching; batch for extraction; per-project budget |
| T7 | Scope creep across nine stages | High | High | Release gates; MVP limited to papers in FILTER; other item types later |
| T8 | Beginners overwhelmed despite levels | Medium | High | Usability rounds in R1; banned-jargon test; one next step at a time |
| T9 | Licensing (PyMuPDF AGPL if adopted; CC-BY-SA dumps; publisher PDFs) | Low–Medium | Medium | GROBID + pypdfium2; store licences; no redistribution of PDFs |
| T10 | Clustering instability makes field maps change between runs | Medium | Low | Fixed seeds; stability tracked; user-pinned directions later |
| T11 | Date metadata is inconsistent across sources (OpenAlex dates unreliable for recency; Crossref month-only or future dates; arXiv announcement lag) | High | High for Latest Research | Separate date claims, authoritative-source rules, *Date uncertain* tab, 3-day fetch overlap, frozen-response test set |
| T12 | Recent papers missing from S2/OpenAlex for days; weak preprint coverage outside arXiv fields | High | Medium | arXiv category sweep, bioRxiv/medRxiv for life sciences (D22) and Crossref; per-source coverage shown |
| T13 | Tutor sounds confident when the paper doesn't support the answer | Medium | High | Scope-first grounding, "not found" status, validator, G-TUTOR unanswerable set, feedback hiding |
| T14 | Tutor cost grows with long conversations | Medium | Medium | Rolling summaries, prompt caching, retrieval budget, per-project LLM budget |
| T15 | arXiv category sweeps are large in busy categories | Medium | Low | Category caps, Stage A prescore before any LLM use, cache |
| T16 | Wrong preprint/journal merges, or missed matches without identifier links | Medium | High (wrong dates and duplicates) | Never merge on title alone; adversarial G-MATCH; possible matches need confirmation; reversible merges with full provenance |
| T17 | D28 lowers recall for papers dated only by secondary sources (venues outside arXiv, bioRxiv/medRxiv and Crossref) | Medium | Medium | Corroboration lookups; *Date uncertain* tab is visible and searchable; recall measured per field |
| T18 | bioRxiv/medRxiv API changes or throttling (no published rate limit) | Low–Medium | Medium | Conservative client, caching, coverage notices; verify terms at implementation |
| T19 | Lesson or check content wrong at beginner level (most trusting users) | Medium | High | Expert rubric per step, answer-key validation, background labelling, "wrong" feedback hides content |
| T20 | Retention bugs (data kept after deletion, or progress lost) | Low | High (trust/privacy) | Cascade rules tested with fixed clocks; deletion audit test; separate confirmed reset for progress |
| T21 | Summaries drift and lose context in long conversations | Medium | Medium | Carried references collected deterministically, not from summary text; long-dialogue test set |
| T22 | Hidden provider lock-in (prompts, schemas or logic tuned to one model) | Medium | Medium | Provider-neutral prompts and schemas; SDK imports confined to adapters; fake-provider swap test (R0-8); per-task evaluation before any model change |
| T23 | Security shortcuts in local mode leak into a hosted deployment | Medium | High | Security scaffolding in R0; non-local bind refused without auth; gate H blockers with tests |
| T24 | Evaluation leakage (the same items used for prompts, calibration and release) inflates results | Medium | High | B0–B3 separation by topic/week/work, hash checks, custodian-run B3, retirement of exposed items |
| T25 | arXiv announcement feed semantics differ from expectations, or capture misses days | Medium | Medium | Verify fields at implementation; record only what the feed shows; fall back to labelled `submission_only`; monitor job success |
| T26 | Too few "verified" dates outside arXiv/bioRxiv/Crossref, so useful papers sit in *Date uncertain* | Medium | Medium | Visible, filterable *Date uncertain* tab with explanations; system-of-record lookups; recall measured per field |
| T27 | Graph drift from PostgreSQL (missed events, partial failures) | Medium | Medium | Outbox, version-guarded idempotent sync, daily reconciliation, full rebuild; sync-lag monitoring |
| T28 | Project data leaking through graph queries (Community Edition has no per-user database security) | Medium | High | Scope on every node/edge; `GraphService` is the only path; named templates only; isolation test suite (R2-16, gate H) |
| T29 | Inferred relationships read as facts in traversals | Medium | High | Assertion property on every edge; `established_only` default policy; weakest-assertion labelling; promotions logged |
| T30 | Operating another stateful service (backups, upgrades, licence) | Medium | Low–Medium | Neo4j is rebuildable from PostgreSQL (no backup dependency); pinned versions; GPLv3 Community Edition reviewed for the deployment model (D34) |

## 7. Decisions

### 7.1 Approved
| # | Decision | Approved approach |
|---|---|---|
| D21 | Latest Research and Ask & Learn in the MVP | **Approved.** Both in R1, as milestones M1c and M1d |
| D22 | bioRxiv and medRxiv | **Approved** for life-science objectives (auto-enabled when the objective maps to life-science categories; toggleable per project); records labelled "Preprint — not peer-reviewed" |
| D23 | Time | **Approved.** UTC for storage and rolling-window calculation (`[now − N×24 h, now)`); display in the user's local time zone; date-only values never shifted across zones |
| D24 | OpenAlex | **Approved.** No paid plan required initially; capability-based client (`OPENALEX_CAPABILITIES=basic` by default, `premium_filters` can be enabled later by configuration) |
| D25 | Release types | **Approved.** "Published version of an earlier preprint" is a separate type and is never presented as new research |
| D26 | Tutor memory and retention | **Approved.** Last 12 turns verbatim + structured summary of older turns with carried evidence references; project memory independent of conversations; deletion and retention controls (ARCHITECTURE §4.10.1–4.10.2) |
| D27 | Tutor scope | **Approved.** General research questions allowed; unrelated requests politely redirected |
| D28 | Unverified dates (**revised** in the architecture review) | **Approved.** Confidence levels verified / corroborated / source agreement / single source / conflicting / uncertain. Only verified (primary, system of record) and corroborated (independent upstream provenance *established*) dates place a paper in a release-type tab; source agreement without established independence, single-source, conflicting and uncertain dates → *Date uncertain* |
| D29 | Preprint/publication matching | **Approved.** Confidence-aware matching (DOI, arXiv ID, explicit version relations, title and author similarity, publication metadata); never on title alone; possible matches linked, not merged; manifestations, source records and date provenance always preserved |
| D13 | Research knowledge graph | **Approved.** Neo4j is a **required, permanent** part of ResearchPilot's long-term architecture, introduced in **R2** as the research knowledge graph. PostgreSQL remains the transactional source of truth; Neo4j is a synchronised graph that can be rebuilt from it. R0–R1 build the graph-ready model and serve R1 graph capabilities through the PostgreSQL `GraphService`. Edition/version/hosting (D34) and Graph Data Science use (D35) remain open |
| — | Date events, preprint labels, tutor boundaries, security gate, staged evaluation | **Required by the architecture review** and reflected in all documents (ARCHITECTURE §4.8, §4.8.7, §4.10.4, §11; EVALUATION_FRAMEWORK §2a–2b) |

### 7.2 Recommended defaults, not yet explicitly approved
| # | Decision | Recommendation |
|---|---|---|
| D1 | LLM provider and models | **Open.** The gateway is provider-independent with task-based model configuration. The initial configuration (Anthropic `claude-opus-5-5` for every task) is **provisional** and labelled as such until approved. Per-task changes only after evaluation |
| D2 | PDF text library | GROBID + pypdfium2 (avoid AGPL PyMuPDF) |
| D3 | Job queue | Postgres-backed queue (also runs the daily retention and arXiv announcement jobs); no Redis in the MVP |
| D4 | Embeddings | Local open model (no API cost); version recorded |
| D5 | Auth | **Revised:** not required for local development (localhost only). Required for any hosted deployment (gate H, §8); security scaffolding is built in R0 |
| D11 | OpenAlex budget | Daily usage budget; free core works with OpenAlex disabled |
| D12 | Vector store | pgvector behind an interface |
| D18 | MVP scope | R1 = Discover, Filter (papers), Latest Research, Learn & Ask, in milestones M1a–M1d |
| D20 | RIE default weights and thresholds | Start with the profiles in RIE §5.2; calibrate on B1 before release |
| D30 | Matching and date thresholds | Start with the thresholds in ARCHITECTURE §4.8–4.8a; calibrate on the B1 splits of G-MATCH and G-LATEST-DATES |
| D31 | arXiv announcement capture | Run the daily feed job from R1 for every mapped category; accept `submission_only` dates for papers announced before capture began |
| D32 | Preprint label for arXiv | Apply "Preprint — not peer-reviewed" to arXiv as well as bioRxiv/medRxiv (accurate; consistent) |

### 7.3 Still open
| # | Decision | Needed by |
|---|---|---|
| D19 | Named people for the evaluation roles (EVALUATION_FRAMEWORK §2b): evaluation lead (approves gold answers), annotators per topic, adjudicators, benchmark custodian (B3). The team can build B0 and the date/match sets; B1–B3 relevance, Latest relevance and tutor sets need domain experts and educators | Evaluation lead and custodian before M1a ends; annotators before M1b calibration |
| D34 | Neo4j edition, version and hosting (Community Edition self-hosted recommended; Enterprise only if clustering or database-level security becomes necessary) | Before R2 |
| D35 | Use of the Neo4j Graph Data Science library for analytics (communities, centrality) versus computing them in the worker | Before R3 |
| D33 | Hosting target and identity provider for gate H (e.g. which OIDC provider, where it runs) | Before any hosted deployment |

## 8. Release blockers

### 8.1 Every release (local or hosted)
1. All honesty gates pass with zero tolerance (EVALUATION_FRAMEWORK §3.3), including: no fabricated citations, quotes, dates or equations; no merges on title alone; no corroboration claimed without recorded provenance; no secondary-only or source-agreement dates shown as confirmed; no journal version of an existing preprint presented as new research; no summaries cited as evidence; no full-text or equation claims beyond a paper's access level.
2. The release's acceptance tests pass (R0-*, R1-*).
3. Metric targets are met on the **B3 held-out benchmark** (R1 interval rule, EVALUATION_FRAMEWORK §2a), or an exception is approved by the evaluation lead; the evaluation report names the approver.
4. Data separation check passes (R1-63).
5. Anti-proxy property tests pass (no tier or action from dates/citations alone).
6. Provider independence check passes (R0-8); the model configuration is labelled provisional unless D1 is approved.
7. Usability round passes (R1, and any release that changes the main flow).
8. **From R2:** graph reconciliation shows no unresolved drift; no inferred or hypothesised relationship is presented as established (UI/API/export check); graph parity and scope-isolation suites pass.
9. **From R1:** relationship-integrity tests pass: single source per type (R1-65), sticky rejection (R1-67), evidence by assertion (R1-68), and minimal deletion markers (R1-69).

### 8.2 Gate H — hosted deployment (any networked access beyond localhost)
Nothing may be deployed where other people or the internet can reach it
until each of these is implemented and tested (ARCHITECTURE §11):

| # | Blocker | Acceptance test |
|---|---|---|
| H1 | Authentication (S1) | Unauthenticated requests to every non-public route return 401 (route inventory); login throttling and lockout work; session cookies are HttpOnly, Secure, SameSite; CSRF tokens enforced |
| H2 | Project-level authorization (S2) | For every route, a member of project A cannot read or change project B (automated horizontal-access suite); viewer cannot edit; row-level security blocks direct SQL across projects |
| H3 | User data isolation (S3) | Caches, embeddings, uploads, exports and knowledge-graph queries never leak across projects (cross-tenant tests); logs contain no user content |
| H4 | Secrets and API keys (S4) | Secret scanning passes; no secret in DB, logs, prompts, error responses (fuzzed error test); rotation procedure documented and rehearsed |
| H5 | Rate limiting and abuse protection (S5) | Per-user/IP limits and LLM/API budgets enforced under load test; uploads and requests above limits rejected; outbound calls stay within provider limits |
| H6 | Secure file access (S6) | Files unreachable without authorization; signed links expire; SSRF tests (private IPs, redirects, non-http schemes) blocked; malformed/oversized PDFs rejected safely |
| H7 | Retention and deletion enforcement (S7) | Deletion and expiry remove data from DB, project caches, embeddings, files and the Neo4j graph (audit test); retention job monitored with alerting; backup retention documented; account deletion removes all user data |
| H8 | Transport and platform (S8) | TLS only; security headers present; dependency and container scans have no unresolved critical findings |

Gate H can be completed any time after R1. It is required before hosting,
not before local use.
