# Agent Design

**Status:** canonical. It consolidates `docs/plan/04` and `docs/plan/11
§11.7–11.8`.

## 1. Agents vs. services

The earlier plan listed 14 "agents", but many did no reasoning: search,
dedup, clustering and citation expansion are ordinary code. Calling them
agents added ceremony and hid which parts are probabilistic. The revised
design separates the two:

- **Services** are deterministic, unit-tested and reproducible.
- **LLM agents** produce probabilistic output. It is always schema-validated,
  evidence-checked and labelled with a claim kind.

LangGraph orchestrates both inside durable workflows. On-demand agents (Tutor,
Card Writer) are called directly by the API.

## 2. Contract (all agents)

```python
class Agent(Protocol[InT, OutT]):
    name: ClassVar[str]
    version: ClassVar[str]
    async def run(self, inp: InT, ctx: AgentContext) -> AgentResult[OutT]: ...

@dataclass
class AgentContext:
    llm: LLMGateway
    repo: ResearchReadRepository      # read access to the record
    sources: SourceRegistry           # for agents allowed to search
    budget: Budget                    # tokens, API calls
    audience: AudienceProfile | None  # level + goal
    logger: BoundLogger

class AgentResult(BaseModel, Generic[OutT]):
    output: OutT | None
    claims: list[ClaimDraft]          # every statement, with kind and evidence
    errors: list[AgentError]
    usage: Usage
```

Rules:
1. Agents never write to the database; workflow nodes persist results
   through repositories.
2. Every output schema is Pydantic. Semantic validators check that item IDs
   exist in the project, that quotes verify and that numbers match evidence.
3. One repair attempt with the validation errors, then a recorded error. No
   silent acceptance.
4. Prompts are versioned files (`prompts/<agent>/<task>.vN.yaml`). The
   version is stored with each output.
5. Agents receive papers as a numbered table (`P1…Pn` → IDs) and may only
   reference those handles.

## 3. LLM agents

| Agent | Responsibility | Inputs → outputs | Mode | Rel. |
|---|---|---|---|---|
| **Planner** | Draft the research objective (core question, sub-questions, tasks, focus concepts, exclusions) and the search plan, in plain language | topic, level, goal → `ResearchObjective` draft + `QueryPlan` | batch | R1 |
| **Relevance Judge** (RIE) | Per sub-question relevance label with a verified quote; second, independent judgement for high-stakes cases | objective + item text → `RelevanceJudgement[]` | batch (top-K) + on demand | R1 |
| **Card Writer** (RIE) | Phrase the six-question recommendation card at the user's level from the deterministic skeleton and evidence only | assessment + evidence + level → `RecommendationCard` | on demand | R1 |
| **Tutor** | Primer, glossary definitions, section/equation/algorithm explanations, worked examples, exercises; enforces grounded/background labelling | subject + level (+ section text) → `Explanation` / `Exercise` | on demand | R1 (primer, terms, sections) / R2 (equations, algorithms, exercises) |
| **Curriculum Builder** | Propose prerequisite edges between concepts; order a learning path with rationales | concepts, glossary, RIE learning-resource tags, level → prerequisite edges + path | batch | R1 |
| **Extractor** | Full-text extraction: contributions, methods, datasets, metrics, results, limitations, assumptions, protocols, compute, method relations | section text → typed extractions with quotes | batch (Batches API eligible) | R2 |
| **Comparator** | Comparison table cell normalisation, improves-on/extends judgements, conflict comparability notes, evolution narrative | extractions + citation contexts → `paper_relations`, table, notes | batch + on demand | R2 |
| **Gap Investigator** | Label limitation clusters; judge overlap and contradiction probe results; draft hypotheses with falsification criteria | gap signals + probe results → gap outcomes, ideas | batch | R3 |
| **Red-Team Reviewer** | Adversarial critique of ideas with its own search budget; prior work, confounds, evaluation flaws, feasibility blockers, triviality | idea + evidence + novelty check → `RedTeamReview` | batch | R3 |
| **Writer** | Section-by-section literature review and proposal prose, constrained to the claims and papers given per section; ablation suggestions; experiment plan narrative | section plan + claims → prose blocks | batch | R4 |

Novelty verification is split between the **Novelty Search** service (real
searches) and the Gap Investigator's overlap judgement. It stays separate from
the Red-Team Reviewer so the critic is independent of the generator.
"Monitor impact" judgements reuse the Gap Investigator's overlap judgement
(R5).

## 4. Deterministic services

| Service | Responsibility | Rel. |
|---|---|---|
| Discovery | Execute query plans per source; normalise records | R1 |
| Deduplicator | Identifier union-find + conservative fuzzy merge; possible duplicates | R1 |
| Enricher | Batch metadata/abstract completion across sources | R1 |
| Citation Explorer | References, citations, recommendations within budgets | R1 |
| Survey Detector | Publication type + title/abstract cues + citation patterns | R1 |
| Signal Engine (RIE) | Compute signals, dimension scores, tiers, role tags; staleness; anti-proxy rules | R1 |
| Override Resolver / Feedback Processor (RIE) | Apply overrides; detect patterns; propose objective edits; bounded weight adaptation | R1 |
| Field Mapper | Embeddings + citation communities → directions; keyword labels; per-direction stats | R1 |
| Term Miner | Candidate terms (corpus-specific noun phrases + entities) → glossary candidates with "appears in" spans | R1 |
| PDF pipeline | Resolve OA location, download, hash, GROBID/LaTeX parse, sections, chunks, embeddings | R1 |
| Quote Verifier / Claim Validator / Citation Validator | Verification (ARCHITECTURE §4.6) | R1 / R4 |
| Novelty Search | Generate and run probe queries (overlap, contradiction, novelty) across sources | R3 |
| Gap Signal Engine | Limitation clustering, intersection matrices, conflict detection | R2–R3 |
| Experiment Resource Resolver | HF/GitHub metadata, link confidence, licences | R4 |
| Report Builder | Structured reports, exports (Markdown, BibTeX, CSV, LaTeX, PDF) | R1 / R4 |
| Journey Guide | Stage readiness and next step | R1 |

## 5. Shared workflow state

Graph state carries IDs and small summaries. Postgres is the source of truth.

```python
class ResearchState(BaseModel):
    project_id: UUID
    run_id: UUID
    objective_id: UUID
    audience: AudienceProfile
    config: RunConfig
    query_ids: Annotated[list[UUID], add] = []
    source_status: Annotated[dict[str, SourceStatus], merge] = {}
    candidate_item_ids: Annotated[list[UUID], add_unique] = []
    included_item_ids: list[UUID] = []
    assessment_stage: Literal["none", "a", "b"] = "none"
    document_status: Annotated[dict[UUID, DocumentStatus], merge] = {}
    gap_ids: list[UUID] = []
    idea_ids: list[UUID] = []
    approvals: Annotated[dict[str, ApprovalDecision], merge] = {}
    errors: Annotated[list[AgentError], add] = []
    budget: BudgetUsage = BudgetUsage()
```

## 6. Workflows

### W1 Discovery (R1)
```
plan_objective (Planner) → ◆ confirm objective & search plan (plain language)
→ search_sources (fan-out per source × query) → dedupe → enrich
→ detect_surveys → assess Stage A (Signal Engine)
→ select_seeds (by Stage A, not by citations alone) → expand_citations
→ dedupe → enrich → assess Stage A
→ ◆ review paper set (tiers + reasons; beginner/advanced views)
→ emit discovery.completed
```

### W2 Assessment (R1; re-run on events)
```
load stale items → Stage A signals → tiers
→ choose top-K + opened/pinned → Relevance Judge (+ cross-check where required)
→ Stage B tiers → mark cards stale
```

### W3 Learning setup (R1)
```
Field Mapper → Term Miner → Curriculum Builder (prerequisites + path)
→ retrieve full text for path papers (PDF pipeline)
```
Explanations and cards are generated on demand (outside workflows).

### W4 Analysis (R2)
```
select included items (priority order by tier) → PDF pipeline
→ Extractor per section group → Quote Verifier → entity normalisation
→ Comparator relations → emit extraction.completed (→ W2 recompute)
```

### W5 Investigation (R3)
```
limitation clusters + intersection matrices + conflicts → gap candidates
→ ◆ review gap candidates
→ per gap: overlap probe + contradiction probe (Novelty Search) → Gap Investigator judgement
→ assess gaps (RIE) → hypotheses (Gap Investigator)
→ per idea: novelty search → Red-Team → (needs_revision → revise, max 2 rounds)
→ assess ideas (RIE) → ◆ select ideas
```

### W6 Experiment design and proposal (R4)
```
resource resolution (datasets, metrics, baselines, models, repos) → RIE assessments
→ experiment plan (Writer for narrative; compute only from compute_reports)
→ ◆ review plan → proposal sections (Writer) → Citation Validator → export
```

### W7 Monitor (R5)
```
scheduled queries → dedupe against project → assess Stage A
→ impact check vs open gaps / accepted ideas (overlap judgement) → alerts
```

## 7. Checkpoints

| Checkpoint | Beginner presentation | Advanced presentation |
|---|---|---|
| Confirm objective & search plan | "Here is what I understood and what I'll search for. Change anything?" | Editable objective fields; raw queries per source |
| Review paper set | Read-first list + "Looks good" | Dense table with tiers, dimension bands, signals |
| Review gap candidates | — (beginners are guided elsewhere) | Signals, probes, evidence for/against |
| Select ideas | Shortlist with plain explanations | Scores, red-team objections, novelty records |
| Review experiment plan | — | Full plan |

Any checkpoint can be set to auto-approve per project.

## 8. Testing

- **Services:** unit and property tests (identifiers, dedup, signals,
  anti-proxy rules, scoring determinism).
- **Agents:** `FakeLLMGateway` fixtures, including malformed outputs,
  unverifiable quotes, unknown IDs and refusals.
- **Workflows:** compiled graphs with an in-memory checkpointer, scripted
  approvals and failure injection (rate limits, a source outage, budget
  exhaustion).
- **Live evaluation:** EVALUATION_FRAMEWORK.
