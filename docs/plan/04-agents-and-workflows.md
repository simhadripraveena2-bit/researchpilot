# 4. Agents and LangGraph workflows

> **Amended by [doc 11 §11.7–11.8](11-architecture-v2.md#117-revised-agent-responsibilities)** (new Tutor, Learning Path Planner, Field Navigator, Project Monitor; merged agents).

## 4.1 Design rules

1. **An agent is a plain, typed, async unit.**
   ```python
   class Agent(Protocol[InT, OutT]):
       name: ClassVar[str]
       version: ClassVar[str]
       async def run(self, inp: InT, ctx: AgentContext) -> AgentResult[OutT]: ...
   ```
   `AgentContext` injects dependencies: `llm: LLMGateway`, `sources:
   SourceRegistry`, `repo: ResearchRepository` (read-only view + write
   commands), `clock`, `logger`, `budget`. Agents never touch LangGraph,
   FastAPI or SQLAlchemy directly, so each can be tested with fakes and
   fixture inputs.
2. **`AgentResult[T]`** = `output: T | None`, `evidence: list[EvidenceRef]`,
   `errors: list[AgentError]`, `metrics` (calls, tokens, cache hits). Partial
   success is normal and explicit.
3. **LangGraph nodes are thin adapters:** read the slice of state the agent
   needs, call `agent.run`, persist outputs through the repository, return a
   state update containing **IDs and summaries only**. Postgres is the source
   of truth; graph state stays small and serialisable.
4. **All LLM outputs are Pydantic models** with semantic validators (IDs
   exist, quotes verify, enums valid). A failed validation triggers one repair
   attempt with the validation error in the prompt; then it is recorded as an
   error, not silently accepted.
5. **Human checkpoints** use LangGraph `interrupt()`; the run status becomes
   `awaiting_approval` and a `checkpoints` row is created. The API resumes the
   graph with `Command(resume=decision)`. Projects can opt to auto-approve
   specific checkpoints.
6. **Durability:** `langgraph-checkpoint-postgres` saver with `thread_id =
   run_id`.

## 4.2 Shared workflow state

```python
class RunConfig(BaseModel):
    sources: list[SourceName] = ["arxiv", "semantic_scholar", "openalex"]
    max_queries: int = 8
    max_results_per_query: int = 50
    max_candidates: int = 400
    latest_window_months: int = 24
    year_range: tuple[int | None, int | None] = (None, None)
    citation_expansion: CitationExpansionConfig  # seeds=15, per_seed=40, depth=1
    use_llm_planner: bool = True
    use_llm_screening: bool = False
    checkpoints: dict[CheckpointName, Literal["require", "auto"]]

class ResearchState(BaseModel):
    # identity
    project_id: UUID
    run_id: UUID
    topic: str
    config: RunConfig

    # planning
    plan: ResearchPlan | None = None           # sub-questions, key concepts, synonyms
    query_ids: Annotated[list[UUID], add] = []

    # discovery
    source_status: Annotated[dict[SourceName, SourceStatus], merge_dicts] = {}
    candidate_paper_ids: Annotated[list[UUID], add_unique] = []
    seed_paper_ids: list[UUID] = []
    expanded_paper_ids: Annotated[list[UUID], add_unique] = []
    included_paper_ids: list[UUID] = []

    # analysis (Phase 3)
    documents: Annotated[dict[UUID, DocumentStatus], merge_dicts] = {}
    extraction_status: Annotated[dict[UUID, ExtractionStatus], merge_dicts] = {}

    # intelligence (Phase 4)
    direction_ids: list[UUID] = []
    gap_ids: list[UUID] = []
    hypothesis_ids: list[UUID] = []

    # outputs & control
    report_id: UUID | None = None
    approvals: Annotated[dict[CheckpointName, ApprovalDecision], merge_dicts] = {}
    errors: Annotated[list[AgentError], add] = []
    budget: BudgetUsage = BudgetUsage()        # LLM tokens, API calls, wall time
```

Reducers (`add`, `add_unique`, `merge_dicts`) make parallel branches (one
per source / per paper) safe to merge.

## 4.3 Agent catalogue

| # | Agent | Input → Output | Uses LLM? | Phase |
|---|---|---|---|---|
| 1 | **Research Planner** | topic, constraints → `ResearchPlan` (sub-questions, key concepts with synonyms, inclusion/exclusion criteria) + `QueryPlan` (per-source query strings with rationale) | Yes (optional; rule-based fallback builds queries from topic + user-supplied keywords) | 2 |
| 2 | **Paper Discovery** | approved `QueryPlan` → search results per source, normalised `PaperRecord`s, dedup into canonical papers, metadata/abstract enrichment | No | 2 |
| 3 | **Citation Exploration** | seed paper IDs → references, citations, S2 recommendations; edges + new candidate papers within budget | No | 2 |
| 4 | **Paper Analysis** | paper with document → contributions, methods, datasets, metrics, results, limitations, each with evidence spans | Yes (+ deterministic quote verification and table parsing) | 3 |
| 5 | **Methodology Comparison** | included papers' extractions → methodology taxonomy, comparison matrix (paper × attribute), differences with evidence | Yes for taxonomy labels; matrix cells are extraction-backed | 4 |
| 6 | **Dataset & Benchmark** | entity mentions → dataset catalogue (normalised, HF links), benchmark tables built only from `reported_results` | Light (entity normalisation) | 3–5 |
| 7 | **Metrics Analysis** | reported results → metric catalogue, which metrics are used where, comparability warnings (different splits/settings) | Light | 3–4 |
| 8 | **Research Gap Discovery** | limitations, directions, entity matrix → `gap_candidates` + probes (§4.6) | Partly | 4 |
| 9 | **Novelty Verification** | hypothesis → independent searches across sources → nearest prior work, overlap judgements with quotes, `novelty_checks` | Yes for overlap judgement; searches are real API calls | 4 |
| 10 | **Research Proposal** | surviving ranked hypotheses + catalogue → experiment plans, proposal document with citations | Yes | 4, 6 |
| 11 | **Red-Team Reviewer** | hypothesis (+ its evidence, novelty check) → objections, counter-evidence searches, verdict | Yes, with its own search budget | 4 |

Supporting (non-agent) services: `Deduplicator`, `MetadataEnricher`,
`Ranker`, `RoleClassifier`, `QuoteVerifier`, `EntityNormalizer`,
`ReportBuilder`, `PdfResolver`, `PdfExtractor`.

## 4.4 Workflow graphs

### A. Discovery workflow (Milestone 1)

```
START
  │
  ▼
plan_research ──(Research Planner)
  │
  ▼
◆ checkpoint: approve_query_plan      user can edit / add / remove queries,
  │                                   change sources and year range
  ▼
search_sources  ── fan-out via Send(): one branch per (source, query)
  │                 each branch: rate-limited, cached, records search_queries
  ▼                 + search_results + source_records; failures → errors[]
normalize_and_dedupe ──(Deduplicator)
  │
  ▼
enrich_metadata  ── batch lookups (S2 /paper/batch, OpenAlex filter by ids,
  │                  Crossref by DOI) to fill abstracts, venues, ids, counts
  ▼
score_relevance ──(Ranker; optional LLM screening)
  │
  ▼
select_seeds  ── top-k by relevance (+ user-pinned papers)
  │
  ▼
expand_citations ──(Citation Exploration)  references + citations + recommendations,
  │                 bounded by budget; new papers go through
  ▼                 normalize_and_dedupe → enrich_metadata → score_relevance again
classify_roles ──(RoleClassifier)  latest / foundational / related, with reasons
  │
  ▼
◆ checkpoint: review_paper_set        user includes/excludes, pins, merges dupes
  │
  ▼
build_report ──(ReportBuilder, deterministic)
  │
  ▼
END  (status: succeeded | partially_succeeded)
```

Every node writes `run_events` so the UI shows live progress ("OpenAlex: 50
results for query 3", "Semantic Scholar rate-limited, retrying in 4 s").

### B. Deep analysis workflow (Phase 3)

```
START → select_papers (included, not yet analysed)
  → fan-out per paper:
       resolve_full_text   (arXiv → S2 openAccessPdf → OpenAlex OA → Unpaywall)
       ├─ unavailable → record failure_reason; analyse abstract only
       └─ download → hash → store
       → extract_structure (GROBID TEI; pdfium fallback) → sections, pages
       → chunk + embed → Qdrant
       → Paper Analysis agent (per section group, structured outputs)
       → QuoteVerifier → persist verified extractions; drop + log unverified
  → normalise_entities (Dataset & Benchmark, Metrics agents)
  → ◆ checkpoint: review_extractions (optional; sample-based spot check)
  → END
```

### C. Research intelligence workflow (Phase 4)

```
START
 → build_directions (paper clustering)          → Methodology Comparison
 → build_comparison_matrix + taxonomy
 → gap pipeline (§4.6, steps 1–6)
 → ◆ checkpoint: review_gap_candidates
 → generate_hypotheses (step 7)
 → for each hypothesis: novelty_verification → red_team_review
       (loop: needs_revision → revise_hypothesis → re-check; max 2 rounds)
 → rank_hypotheses (step 9)
 → ◆ checkpoint: select_hypotheses
 → experiment_plans → proposal draft
 → END
```

### D. Report workflow (Phase 6)
Assemble sections from the record → LLM writes prose *per section* given only
the claims/papers for that section → `CitationValidator` checks each sentence
has citations that resolve to project papers and that cited claims exist →
render Markdown → export (BibTeX, LaTeX, PDF).

## 4.5 Checkpoint catalogue

| Checkpoint | Workflow | Human sees | Human can |
|---|---|---|---|
| `approve_query_plan` | A | plan, queries per source with rationale | edit/add/remove queries, change sources, filters |
| `review_paper_set` | A | ranked candidates with roles and reasons, possible duplicates | include/exclude, pin as seed, merge/split, trigger one more expansion round |
| `review_extractions` | B | sampled extractions with quotes highlighted | accept, correct, reject (feeds evaluation set) |
| `review_gap_candidates` | C | candidates with computed signals and probe results | discard, prioritise, add own gap |
| `select_hypotheses` | C | ranked hypotheses, red-team objections, novelty checks | choose which to turn into proposals |

## 4.6 Research-gap discovery pipeline

The pipeline produces gap candidates from **computed signals** over the
research record; the LLM is used to label, phrase and critique, not to invent
gaps.

| Step | What happens | Method | Output (stored) |
|---|---|---|---|
| 1. Extract limitations | Per paper, author-stated limitations, future work, threats to validity | Paper Analysis agent; each item needs a verified quote; `stated_by=authors` vs `inferred` | `limitations` |
| 2. Recurring limitations | Cluster limitations semantically; a cluster is *recurring* if it spans ≥ N papers (default 3) from ≥ 2 distinct author groups (to avoid one lab repeating itself) | Embeddings + HDBSCAN/agglomerative; LLM writes cluster label from member quotes | `limitation_clusters`, gap candidates of kind `recurring_limitation` |
| 3. Research directions | Group papers | Hybrid: bibliographic coupling + co-citation graph communities (Leiden) combined with embedding clusters; LLM labels each direction from member titles | `research_directions` |
| 4. Underexplored intersections | Build count matrices: direction × method, method × dataset, task × metric, direction × limitation-cluster. Flag cells with low observed count relative to the expectation from row/column marginals (e.g. standardised residual ≤ −2, both marginals above threshold) | Deterministic statistics; numbers stored in `signal` | gap candidates of kind `sparse_intersection` |
| (4b) Conflicts | Same (method, dataset, metric, setting) with materially different reported values across papers; or contradictory claims | From `reported_results`; comparability checks (split, setting) | gap candidates of kind `conflicting_results` |
| 5. Probe intersections | For each candidate, generate targeted queries and search all sources **outside** the current corpus | Real API searches recorded as `search_queries(origin=gap_probe)` | `gap_probes` |
| 6. Existing / conflicting work | For top probe results, judge overlap with the gap, quoting the abstract/text that shows overlap | LLM judgement constrained to retrieved text; outcome `no_close_match`, `partial_overlap`, `already_addressed` | updated gap status |
| 7. Generate hypotheses | Only for gaps with status `open` or `partial_overlap`; each hypothesis must cite its gap ID, the supporting evidence IDs and state falsification criteria | LLM with structured output | `hypotheses` (kind `ai_hypothesis`) |
| 8. Red-team | Separate agent prompted adversarially: prior work it can find (with its own search budget), confounds, evaluation flaws, feasibility blockers, triviality | LLM + searches | `hypothesis_reviews` |
| 9. Rank | Scores for evidence strength, novelty, significance, feasibility; each score has rule-based components (e.g. novelty from probe/novelty-check outcomes and similarity of nearest work; feasibility from dataset availability, compute estimate, code availability) plus an LLM rationale; weights configurable and shown | `hypothesis_scores` |

Wording rules for outputs: "No closely matching work found in 14 searches
across arXiv, Semantic Scholar and OpenAlex (2026-11-10)" — never "novel".

## 4.7 Evidence and anti-fabrication mechanics

- **QuoteVerifier:** normalises Unicode (NFKC), whitespace, ligatures and
  end-of-line hyphenation on both sides, then searches the section text; a
  fuzzy fallback (≥ 0.95 similarity over a sliding window) is allowed only to
  absorb extraction noise and is flagged `verified_fuzzy`. Records page and
  offsets.
- **Reference constraint:** LLM schemas use `paper_ref: PaperRef` (an internal
  ID or a short handle like `P17` mapped from a table given in the prompt).
  Validators reject handles not in the table.
- **Numbers:** `reported_results.value_text` must appear in the evidence
  quote; parsed `value` must equal the numeric content of `value_text`.
- **Labels everywhere:** every claim carries `kind`; the report renderer
  refuses to emit a claim without kind and evidence (except `ai_hypothesis`,
  which must cite the gap and evidence it was derived from).
- **Evaluation set (Phase 3+):** a small hand-labelled set of papers with
  expected extractions; CI runs the extraction pipeline against recorded LLM
  outputs, and a scheduled job runs it against the live model to track
  precision/recall of extractions and quote-verification rate.

## 4.8 Testing agents

- Unit: each agent with `FakeLLMGateway`, fake `SourceRegistry` backed by
  recorded fixtures, in-memory repository. Assert outputs, evidence links and
  error handling (e.g. a 429 storm on one source).
- Graph tests: compile each graph with in-memory checkpointer; drive through
  interrupts with scripted approvals; assert final state and persisted rows.
- Property tests (Hypothesis library) for dedup and identifier normalisation.
