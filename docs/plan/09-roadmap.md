# 9. Implementation roadmap and acceptance criteria

> **Superseded for ordering and scope by [doc 14](14-mvp-and-roadmap.md).** Phase 1–2 acceptance criteria are reused as R0/R1; later criteria move to R2–R5.

Each phase ends with a demo, a tagged release, passing CI, and updated docs.
A phase is not started until the previous phase's acceptance criteria pass.
Phases are split into small PR-sized steps.

## Milestone 1 = Phase 1 + Phase 2

> User enters a topic → search multiple academic sources → deduplicate →
> retrieve metadata and abstracts → explore related papers → save results →
> display a cited research-paper report.

### Milestone 1 report contents (deterministic, no LLM prose)

1. **Header:** topic, run ID, date, sources used, config summary.
2. **Summary statistics** (computed): candidates found per source, after
   dedup, included; year distribution; OA share; source overlap.
3. **Search log:** every query sent, per source, with result counts, status
   and timestamps.
4. **Latest publications:** sorted by date, with relevance reason.
5. **Foundational papers:** with the stated reason (in-corpus citations,
   global citations with source and date).
6. **Related work:** remaining included papers, grouped by discovery path
   (search / reference / citation / recommendation).
7. **Citation network summary:** most-connected papers, link to graph view.
8. **Coverage & limitations:** failed/degraded sources, budget exhaustion,
   missing abstracts count, possible duplicates pending review.
9. **References:** every paper with authors, title, venue, year, DOI link,
   arXiv ID link, S2/OpenAlex URLs.

Optionally (if LLM configured and enabled): an "AI synthesis" executive summary,
clearly badged, where each sentence must cite included papers and is validated
against the reference constraint. Off by default in M1.

---

## Phase 1 — Foundation

**Steps**
1. Repo scaffolding, tooling, pre-commit, CI skeleton.
2. Backend app factory, settings, structured logging, problem+json errors, health endpoints.
3. Postgres + Alembic; `projects`, `research_runs`, `run_events`, `checkpoints` tables.
4. Projects CRUD API + dashboard endpoint.
5. Worker (arq + Redis) with a no-op workflow run; SSE event stream.
6. Frontend shell: layout, routing, typed API client, Dashboard, New Project, Project overview, Run view (progress stream).
7. Docker Compose for all services; `make up` works from a clean clone.

**Acceptance criteria**
- [ ] `cp .env.example .env && make up` starts postgres, redis, api, worker, frontend; all healthchecks green.
- [ ] `GET /api/v1/health/ready` returns 200 only when DB and Redis are reachable; returns problem+json 503 otherwise.
- [ ] Projects can be created, listed, edited and archived via API and UI; data survives container restarts.
- [ ] Starting a dummy run shows live progress events in the UI via SSE, and the run reaches `succeeded`; killing the worker mid-run and restarting it resumes or fails the run with a clear status (no zombie "running" runs).
- [ ] Logs are JSON with `run_id`/`project_id` context; a test asserts that configured secrets never appear in logs.
- [ ] CI runs lint, type-check, unit + integration tests (backend and frontend) and Docker builds; all green.
- [ ] Migrations upgrade from empty and downgrade cleanly.

## Phase 2 — Literature discovery (completes Milestone 1)

**Steps**
1. Domain models + identifier normalisation (DOI, arXiv, S2, OpenAlex) with property tests.
2. `SourceClient` base: rate limiting, retries, circuit breaker, HTTP cache, source record storage.
3. arXiv integration (search + parser) with recorded fixtures.
4. Semantic Scholar integration (search, batch, references, citations, recommendations).
5. OpenAlex integration (search, batch by IDs, abstract reconstruction, usage budget).
6. Crossref integration (DOI lookup / validation).
7. Papers schema (`papers`, `paper_identifiers`, authors, `citations`, `project_papers`, `search_queries`, `search_results`, `source_records`, merges).
8. Deduplicator (identifier union-find + conservative fuzzy) and metadata enrichment.
9. Research Planner agent (LLM + rule-based fallback) and `approve_query_plan` checkpoint.
10. Discovery graph: search fan-out, dedup, enrichment, ranking, seed selection, citation expansion, role classification, `review_paper_set` checkpoint.
11. Report builder (structured JSON → Markdown, BibTeX, CSV export).
12. UI: query plan editor, paper set review, Paper Explorer, paper drawer with provenance, citation graph, Research Search, Saved Papers, report view, Project History.

**Acceptance criteria**
- [ ] For a reference topic set (5 topics across CS/ML, biomedicine, physics), a run completes end-to-end against live APIs and in fixture mode.
- [ ] **No duplicates by identifier:** the DB constraint holds; a test feeds the same paper via arXiv, S2 (with DOI + arXiv IDs) and OpenAlex and gets exactly one canonical paper with all identifiers attached.
- [ ] Dedup quality on a labelled set of ≥ 200 record pairs: precision ≥ 0.99 (wrong merges are worse than missed ones), recall ≥ 0.90; ambiguous pairs surface in the duplicates view.
- [ ] Every paper in the report has at least one resolvable link (DOI, arXiv or source URL), and every displayed field has recorded provenance (`field_sources` + source record).
- [ ] Every query sent is listed in the search log with source, exact string, parameters, count, status; re-opening the run later shows the same data.
- [ ] Rate limiting verified by tests: arXiv client never exceeds 1 request/3 s; S2 client respects configured RPS; 429 with `Retry-After` is honoured; a source returning 500s repeatedly is marked degraded and the run finishes as `partially_succeeded` with a coverage notice.
- [ ] With **no LLM key configured**, the workflow still completes using the rule-based planner.
- [ ] Planner LLM output is schema-validated; malformed output triggers one repair attempt then a recorded error and fallback — covered by tests with the fake gateway.
- [ ] Both checkpoints pause the run (`awaiting_approval`), survive a worker restart, and resume with user edits applied (e.g. a removed query is not executed).
- [ ] Citation expansion respects budgets (seeds × per-seed limit) and records each edge's source; expanded papers show "found via reference of X".
- [ ] Role classification stores a human-readable reason for every latest/foundational label.
- [ ] Re-running discovery on the same project with a warm cache makes zero network calls for cached requests (asserted via cache hit counters) and produces the same paper set given the same query plan.
- [ ] Report exports (Markdown, BibTeX, CSV) round-trip: BibTeX parses with a standard parser; every entry has DOI or eprint (arXiv) when known.
- [ ] Integration docs exist for arXiv, S2, OpenAlex, Crossref with verified-on dates.
- [ ] Playwright e2e (fixture mode): create project → approve plan → review paper set → view report → save paper → find it in Saved Papers.

## Phase 3 — Deep paper analysis

**Steps:** PDF resolver chain (arXiv → S2 OA → OpenAlex OA → Unpaywall → optional OpenAlex full-text, budget-gated) → downloader (size/type checks, content addressing) → GROBID + pdfium extraction → sections/pages → chunking + embeddings + Qdrant → Paper Analysis agent (contributions, methods, datasets, metrics, results, limitations) → QuoteVerifier → entity normalisation → user PDF upload → UI: full-text status, extractions with quotes, PDF viewer with highlight, dataset/metric catalogue v1.

**Acceptance criteria**
- [ ] For every included paper, full-text status is one of `retrieved` or `unavailable/failed` with a specific reason code shown in the UI; no paper silently lacks a status.
- [ ] 100% of persisted extractions have an evidence span with `verified=true` (or `verified_fuzzy` flagged); unverified extractions are counted and logged, never shown.
- [ ] Every `reported_results` row's `value_text` appears inside its evidence quote (enforced and tested).
- [ ] Evidence spans for body text carry page numbers; clicking one opens the PDF at that page with the quote highlighted (where coordinates exist).
- [ ] On the evaluation set (≥ 30 OA papers, hand-labelled): dataset mention precision ≥ 0.90, recall ≥ 0.75; limitation precision ≥ 0.85; reported-result tuple precision ≥ 0.90. Numbers are tracked in CI from recorded outputs and periodically against the live model.
- [ ] When full text is unavailable, analysis runs on the abstract and every output from it is labelled "abstract only".
- [ ] Re-processing the same PDF (same sha256) reuses stored TEI and extractions unless the extractor version changed.
- [ ] Semantic search returns passages with paper, section and page.

## Phase 4 — Research intelligence

**Steps:** research directions (citation-graph communities + embeddings) → methodology taxonomy & comparison matrix → limitation clustering → intersection matrices & sparsity signals → conflicting-results detection → gap probes (real searches) → existing-work judgement → hypothesis generation → novelty verification → red-team review loop → ranking → experiment plans → UI: Methodology Comparison, Gap Explorer, Research Ideas, Proposal draft.

**Acceptance criteria**
- [ ] Every gap candidate stores its computed signal (counts, residuals, member papers) and is reproducible from stored data.
- [ ] "Recurring limitation" gaps reference ≥ N papers from ≥ 2 author groups, each with a verified quote.
- [ ] Every gap has at least one probe with real recorded queries; gaps with `already_addressed` link the addressing paper(s) with a quote.
- [ ] Every hypothesis links to its gap, its supporting evidence, a novelty check (queries, sources, date, nearest papers) and ≥ 1 red-team review.
- [ ] No UI text or export says a hypothesis is "novel" or "guaranteed"; a test scans outputs for banned phrasings; novelty wording follows the template.
- [ ] Scores show components with explanations; changing weights re-ranks without re-running LLM calls.
- [ ] Comparison matrix cells link to evidence; empty cells are shown as "not reported", not guessed.
- [ ] Graph tests drive the red-team revise loop through at least one `needs_revision` round with the fake LLM.

## Phase 5 — External integrations

**Steps:** Hugging Face (paper pages, models, datasets, Spaces) → GitHub (repo metadata, search, README confirmation) → code link resolution with confidence levels → dataset catalogue enrichment with HF datasets → model/dataset comparison views → optional Papers with Code archive import.

**Acceptance criteria**
- [ ] Each code/HF link records its link source and confidence; name-search-only matches are labelled "possible".
- [ ] Repository metadata (stars, licence, last push, archived) shows fetched-at dates.
- [ ] GitHub search stays within rate limits (tested), with graceful degradation when the token is missing.
- [ ] Dataset entities link to HF datasets only when matched by ID/URL or confirmed alias; ambiguous matches go to review.

## Phase 6 — Research reports

**Steps:** section planner → per-section writer constrained to that section's claims/papers → `CitationValidator` (every factual sentence cites ≥ 1 project paper; cited claim exists; numbers match `reported_results`) → full report per spec (executive summary through references) → proposal generator → Markdown/LaTeX (BibTeX) export → PDF via LaTeX (tectonic) or HTML-to-PDF → reference management (BibTeX/RIS/CSL-JSON).

**Acceptance criteria**
- [ ] Reports contain all sections listed in the requirements; empty sections say why (e.g. "no benchmark results extracted").
- [ ] Citation validator: 100% of citations resolve to project papers; sentences without citations in factual sections are flagged and either fixed or removed before publishing.
- [ ] Every number in a report traces to a `reported_results` row or a computed statistic.
- [ ] Claim kinds are visually distinguished in HTML/PDF and labelled in LaTeX (e.g. margin markers/footnotes).
- [ ] LaTeX export compiles without errors in CI; references include DOI / arXiv ID / URL.
- [ ] Reports are versioned and immutable; regenerating produces a new version with a diff view.

## Phase 7 — Advanced capabilities

**Steps:** Neo4j projection + graph UI → scheduled monitors (re-run saved queries, diff new papers) → incremental updates to directions/gaps → project memory → cross-project discovery → authentication (D5) → backups/runbook.

**Acceptance criteria**
- [ ] Neo4j can be dropped and fully rebuilt from Postgres; graph relationships carry Postgres IDs/evidence IDs.
- [ ] Monitors run on schedule, are idempotent, and notify only on genuinely new canonical papers.
- [ ] Incremental update re-uses prior extractions and marks which conclusions changed.
- [ ] Cross-project suggestions explain why (shared entities/citations).

---

## Testing strategy (all phases)

| Layer | Approach |
|---|---|
| Unit | pure functions (identifiers, dedup, ranking, quote verification), agents with fakes |
| Integration clients | `respx` with recorded, sanitised fixtures; malformed/edge payload cases; rate-limit/retry behaviour with a fake clock |
| DB | Postgres in Docker; repository tests; migration up/down |
| Workflow | compiled graphs with in-memory checkpointer, scripted approvals, failure injection |
| API | FastAPI TestClient/httpx against test DB; OpenAPI schema snapshot |
| Frontend | Vitest + Testing Library + MSW; Playwright e2e against fixture-mode backend |
| Live contract | `pytest -m live`, opt-in, nightly: verifies each external API still matches our parser expectations |
| Quality eval | extraction eval set (Phase 3+), gap/hypothesis rubric review (Phase 4+) |

## Proposed first implementation steps after approval

1. Phase 1 steps 1–3 in one PR (scaffold, settings/logging, DB + migrations).
2. Phase 1 steps 4–7 in a second PR (API, worker, SSE, frontend shell, compose).
3. Then Phase 2 in roughly 6 PRs following the step order above, each with tests.
