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
0. Agents request a **task** from the LLM gateway (e.g. `relevance_judge`),
   never a provider or model. Provider and model come from the task
   configuration, which is provisional until D1 is approved (ARCHITECTURE
   §4.2).
0b. **Agents never touch Neo4j.** They read graph structure only through
   `GraphService`, with an explicit assertion policy and project scope. The
   relationships they produce are persisted (by workflow nodes, rule 1,
   through `RelationWriter`) only to PostgreSQL; Neo4j receives them through sync. An LLM-proposed
   relationship is stored as `assertion = inferred` (or `hypothesized`) with its evidence
   and confidence, and is promoted only by verification or the user. LLMs
   never compose graph queries; they can only trigger named, parameterised
   patterns.
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
| **Planner** | Draft the research objective (core question, sub-questions, tasks, focus concepts, exclusions) and the search plan, in plain language; for Latest Research, per-subtopic recent-search queries and an arXiv category mapping (user-editable) | topic, level, goal → `ResearchObjective` draft + `QueryPlan` (+ `LatestScanPlan`) | batch | R1 |
| **Relevance Judge** (RIE) | Per sub-question relevance label with a verified quote; `relation_to_project` (extends / alternative to / challenges / overlaps with / unrelated, naming the project item, with a quote); second, independent judgement for high-stakes cases | objective + item text (+ saved/Essential project items) → `RelevanceJudgement[]` | batch (top-K) + on demand | R1 |
| **Card Writer** (RIE) | Phrase the six-question recommendation card at the user's level from the deterministic skeleton and evidence only; for recent items, the **Latest brief** (eight questions, RIE §10.2) and "What's new"; **digest mode** writes the Latest Research "What's new this week" digest from the scan's top verified statements | assessment + evidence + level → `RecommendationCard` / `LatestBrief`; scan skeleton → `Digest` | on demand + W8 | R1 |
| **Tutor** (powers **Ask & Learn**) | **Answer mode:** conversational answers about concepts, papers, methods, datasets, directions; seven styles; follow-up intents; missing prerequisites. **Teaching mode:** builds a progressive lesson plan (intuition → example → technical → mathematical → algorithmic → paper connection → implementation → understanding check), generates one step at a time, adapts on "simpler"/"deeper"/jump, writes and grades short checks (short answers labelled AI-graded). **Summary task:** recaps older turns as context only. Enforces grounded/background labelling and "not found in sources" | question or lesson action + view context + project memory + retrieved evidence + conversation memory + level/style → `TutorAnswer` / `LessonStep` / `ConversationSummary` | on demand, streamed | R1 (concepts, papers, sections, follow-ups, styles, lessons, checks) / R2 (paper equations via LaTeX, algorithm walkthroughs grounded in extractions, exercises, multi-paper questions) |
| **Curriculum Builder** | Propose prerequisite edges between concepts; order a learning path with rationales | concepts, glossary, RIE learning-resource tags, level → prerequisite edges + path | batch | R1 |
| **Extractor** | **Abstract mode (R1):** main contribution; any method/dataset/benchmark *stated in the abstract*; the paper's own comparative statements ("outperforms…", "unlike prior work…"); author-stated limitations, open problems or future work. Quotes verified against the abstract. **Full-text mode (R2):** contributions, methods, datasets, metrics, results, limitations, assumptions, protocols, compute, method relations | abstract or section text → typed extractions with quotes | batch (Batches API eligible) | R1 (abstract) / R2 (full text) |
| **Comparator** | Comparison table cell normalisation, improves-on/extends judgements, conflict comparability notes, evolution narrative | extractions + citation contexts → `research_relations` rows (EXTENDS / CONTRADICTS / RELATED_TO, via `RelationWriter`), table, notes | batch + on demand | R2 |
| **Gap Investigator** | Label limitation clusters; judge overlap and contradiction probe results; draft hypotheses with falsification criteria | gap signals + probe results → gap outcomes, ideas | batch | R3 |
| **Red-Team Reviewer** | Adversarial critique of ideas with its own search budget; prior work, confounds, evaluation flaws, feasibility blockers, triviality | idea + evidence + novelty check → `RedTeamReview` | batch | R3 |
| **Writer** | Section-by-section literature review and proposal prose, constrained to the claims and papers given per section; ablation suggestions; experiment plan narrative | section plan + claims → prose blocks | batch | R4 |

Novelty verification is split between the **Novelty Search** service (real
searches) and the Gap Investigator's overlap judgement. It stays separate from
the Red-Team Reviewer so the critic is independent of the generator.
"Monitor impact" judgements reuse the Gap Investigator's overlap judgement
(R5).

**No new agents were added for Latest Research or Ask & Learn.** Latest
Research reuses Planner, Relevance Judge, Card Writer and Extractor (abstract
mode). Ask & Learn is the conversational mode of the existing Tutor, plus
deterministic context and retrieval services.

### 3.1 Tutor answer contract

```python
class TutorAnswer(BaseModel):
    paper_access_levels: dict[str, AccessLevel]   # per paper handle, from the Context Builder (not model-chosen)
    scope_used: Literal["about_this_paper", "about_project", "general"]
    answer_status: Literal["grounded", "partially_grounded", "background_only",
                           "not_found_in_sources", "out_of_scope"]
    blocks: list[AnswerBlock]            # ordered; each is one claim
    not_found: list[str]                 # what the sources did not contain
    missing_prerequisites: list[str]     # concept names → matched to glossary/concepts
    suggested_followups: list[FollowUpIntent]

class LessonStep(BaseModel):
    step: Literal["intuition", "simple_example", "technical", "mathematical",
                  "algorithmic", "paper_connection", "implementation", "understanding_check"]
    skipped_reason: str | None           # e.g. "No standard mathematical formulation"; "No paper in view"
    answer: TutorAnswer | None           # the step content, same block/claim rules
    checks: list[CheckQuestion] | None   # only for understanding_check
    next_options: list[Literal["next", "simpler", "deeper", "jump", "ask", "stop"]]

class AnswerBlock(BaseModel):
    kind: ClaimKind                      # reported_finding | extracted_observation | ai_interpretation
    grounding: Literal["grounded", "background"] | None
    style: ExplanationStyle              # intuitive | step_by_step | technical | mathematical |
                                         # practical_example | code | comparison
    text: str                            # Markdown; LaTeX allowed in $…$
    evidence: list[str]                  # handles E1…En from the retrieval table only
    equation_refs: list[str]             # equation handles from the provided table only
    code: CodeBlock | None               # language, source; always "not run"
```

Validation (ClaimValidator):
- `grounded` blocks must cite at least one provided evidence handle, and
  quoted text must verify.
- Equations attributed to a paper must match an `equations` row or the user
  selection exactly (after LaTeX normalisation). Otherwise the block is
  rejected.
- Paper-attributed blocks must be consistent with the paper's **access
  level**: no full-text claims when only the abstract is accessible; no
  equation explanation unless that equation's text is available. The
  `access_level` used is stored on the message and shown in the UI.
- If `scope_used = about_this_paper` and no block is grounded, then
  `answer_status` must be `not_found_in_sources` or `background_only`, and the
  UI shows "Not found in the available text of this paper" first.
- `background` blocks may not name papers, authors, results or numbers with
  units unless they resolve to project items.
- Evidence handles may only point to evidence spans, chunks, equations or
  items. Pointing to a conversation summary or an earlier assistant message
  is rejected.

## 4. Deterministic services

| Service | Responsibility | Rel. |
|---|---|---|
| Discovery | Execute query plans per source; normalise records | R1 |
| Deduplicator + **Version Matcher** | Identifier union-find; confidence-aware preprint↔publication matching from decisive identifier links, strong source links and supporting/contradicting evidence; **never merges on title similarity alone**; matched manifestations are attached to one work but stay distinct (identifiers, dates, documents, evidence keep their manifestation); possible matches linked, not merged; user decisions final; reversible (ARCHITECTURE §4.8a, D29) | R1 |
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
| Date Resolver | Store each date **event** per manifestation with reporting source and upstream provenance (never guessed); look up the system of record; derive first public appearance and its basis (announced / posted / published online / issue / issued / submission_only); confidence verified / corroborated (independent provenance established) / source agreement / single source / conflicting / uncertain (D28 revised); classify release type; UTC computation, boundary-day flags (ARCHITECTURE §4.8) | R1 |
| arXiv Announcement Capture | Daily job reading arXiv announcement feeds for mapped categories; writes `arxiv_announcement_log` and `preprint_announced`/`version_announced` events; upgrades `submission_only` bases (ARCHITECTURE §4.8.5) | R1 |
| Latest Scan Planner | Turn the objective + Planner's `LatestScanPlan` into date-bounded source queries (arXiv category sweep + topic queries; bioRxiv/medRxiv `/details` + `/pubs` for life-science objectives; S2; OpenAlex per configured capabilities; Crossref); UTC window + overlap | R1 |
| Related Item Linker | Link recent papers to project items: `cites` (citation data) vs `similar` (embedding similarity, labelled) | R1 |
| Evidence Retriever | Hybrid retrieval (pgvector + Postgres full-text) over chunks, sections, equations and extractions, scoped to paper → project; returns numbered evidence handles | R1 |
| Context Builder | Assemble project memory (objective, saved items, notes, saved explanations, concept progress, learning path), view context and conversation memory (last 12 turns + summary + carried references re-resolved to original passages) within a token budget; computes each paper's **access level** (metadata only / abstract only / full text processed / full text failed / equations available) that bounds what the Tutor may claim (ARCHITECTURE §4.10.4) | R1 |
| Action Recommender (RIE) | Deterministic read now / save for later / deprioritise / check manually rule from tier, relations and links; never uses dates or citation counts | R1 |
| Learning Progress Tracker | Update `concept_progress` from lesson steps and checks; emit `concept_progress.updated` | R1 |
| Retention Enforcer | Daily job applying each project's tutor retention policy; deletion cascades as specified (ARCHITECTURE §4.10.2) | R1 |
| **GraphService** (interface) | The only access path to graph queries for agents, services and APIs: neighbours, paths, subgraphs, related work, named patterns, provenance trails; assertion policy and project scope required on every call. PostgreSQL implementation for the R1 capability set (citation graph, versions, 1-hop neighbours, basic related papers); Neo4j implementation from R2 (required) for multi-hop traversal and rich exploration, and from R3 for gap, contradiction and novelty patterns; unsupported capabilities return `capability_unavailable` (ARCHITECTURE §12.8) | R0 (interface + PostgreSQL) / R2 (Neo4j) |
| **RelationWriter** | The single write path for every relationship table, research and structural (`research_relations`, `structural_relations`, `entity_links`, `citations`, …): registry lookup (one source per type), endpoint-rule and cardinality checks, **project-scope validation** (no cross-project links; explicit `ProjectScope` from the caller; database trigger is authoritative), project-scoped overlays for user decisions on global relationships, natural-key upserts, evidence-by-assertion checks, sticky rejection (automatic writes to rejected rows become logged no-ops), suppression fingerprints, assertion-change log, deletion markers (ARCHITECTURE §12.4–12.5) | R1 |
| Relation Registry + Graph Projector | `relation_registry` + `relation_endpoint_rules` (one source per type; declared non-sources); map PostgreSQL rows to graph nodes/edges with stable `uid`, assertion, confidence, evidence, provenance and scope; never project declared non-sources (derived analytics, snapshots, project memory, learning data); eligibility rules (validated records only) | R1 (registry) / R2 (projector) |
| Graph Sync Worker | Consume outbox events (incl. tombstones), re-project current state, idempotent version-guarded MERGE into Neo4j, retries, dead letters | R2 |
| Graph Reconciler | Scheduled count/hash comparison per label and relationship type, repair, orphan removal, blue/green full rebuild | R2 |
| Scope Router | Pick the default scope (anchored view → about_this_paper; project page → about_project; otherwise general); the user can override | R1 |

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
schedule → W8 Latest scan (same workflow) → impact check vs open gaps /
accepted ideas / running experiments (overlap judgement) → alerts + notifications
```

### W8 Latest Research scan (R1)
```
load objective version → Latest Scan Planner (queries per subtopic; arXiv categories;
bioRxiv/medRxiv categories if enabled; window in UTC + 3-day overlap; OpenAlex capabilities)
→ search_sources (fan-out, date-bounded) → Deduplicator + Version Matcher (sources + project)
→ system-of-record lookups (Crossref / arXiv / bioRxiv by identifier) → Date Resolver
  (events → provenance → confidence → first public appearance → release type)
→ assess Stage A (all) → Stage B top-K + relation_to_project (challenges cross-checked)
→ Extractor (abstract mode, top-K) → Related Item Linker → Action Recommender
→ Card Writer (Latest brief: 8 answers) → ClaimValidator
→ store scan + entries + briefs → emit latest_scan.completed
```
No human checkpoint by default; the scan plan can be reviewed in the scan
settings. Partial results are stored with per-source coverage.

### Ask & Learn request flow (on demand, not a workflow)
```
message → Context Builder (project memory + view context + last 12 turns
          + summary + carried refs re-resolved to original passages)
→ Scope Router → Evidence Retriever
→ explanation cache lookup (canonical asks and non-anchored lesson steps)
→ Tutor (answer mode or lesson step) → ClaimValidator
→ stream → persist message, evidence links, claims
→ teaching mode: update teaching_sessions + concept_progress
→ when turns beyond the last 12 accumulate: Tutor summary task → conversation_summaries
  (summary_text + carried_refs extracted deterministically from the evidence links)
```
`carried_refs` are collected **deterministically** from
`tutor_message_evidence` and saved explanations, not from the summary text,
so a summary can never add or lose an evidence reference.

### W9 Graph synchronisation and reconciliation (R2)
```
domain_events (incl. tombstones) → Graph Sync Worker → load current PG state
→ Graph Projector (eligibility, uid, assertion, evidence) → Neo4j MERGE (version-guarded)
→ graph_sync_state; failures → retries → graph_dead_letters
daily: Graph Reconciler → compare counts/hashes → re-project or delete → graph_sync_runs
on demand: full rebuild into a fresh database → switch over
```

### 6.1 Graph use by agents and services

| Agent / service | Graph use | From |
|---|---|---|
| Field Mapper, Related Item Linker | Citation communities, co-citation, related items via `GraphService` (PostgreSQL implementation) | R1 |
| Comparator | `EXTENDS` / `CONTRADICTS` chains for evolution timelines and conflict context | R2 |
| Gap Signal Engine + Gap Investigator | Named patterns: method × dataset structural holes, limitations propagated along `EXTENDS`, weakly connected directions; results stored as `computed` signals with `graph_query_log` reference | R3 |
| Novelty Search + Red-Team Reviewer | Graph neighbourhood of a hypothesis (shared methods, datasets, limitations; `CONTRADICTS` paths) searched **before** external probes; inferred edges only with `include_inferred` and labelled | R3 |
| Writer (proposals) | Provenance trail: proposal → hypothesis → gap → limitations → papers → evidence | R4 |
| Project Monitor | Impact detection: new paper → `ADDRESSES`/`CONTRADICTS`/`EXTENDS` paths → accepted hypotheses, open gaps, experiments | R5 |

No new LLM agents are needed for the graph. Relationships the agents
already produce (relevance relations, extraction mentions, comparator
relations, gap outcomes, red-team counter-evidence) are written to
PostgreSQL with assertion metadata and reach Neo4j through sync.

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
- **Date Resolver:** table-driven tests for every release-type rule,
  window boundaries, precision, conflicts and future dates (EVALUATION_FRAMEWORK §3.8).
- **Tutor:** scripted multi-turn dialogues with the fake gateway (context
  retention beyond 12 turns via summaries, scope switching, not-found
  handling, equation-fabrication rejection, summary-as-evidence rejection),
  lesson flows (next, simpler, deeper, jump, interrupt and resume, skipped
  steps, checks).
- **Date Resolver:** G-LATEST-DATES cases for source agreement vs
  independent corroboration, submission-only arXiv dates, announcement
  capture, journal versions of existing preprints, and every event type.
- **Tutor access levels:** fixtures at each access level; assertions that
  no full-text or equation claims appear below the required level.
- **Version Matcher:** G-MATCH pairs, including adversarial similar-title
  pairs; property test that title-only evidence never yields a match.
- **Retention:** deletion and expiry cascades, and survival of saved
  explanations and progress.
- **Live evaluation:** EVALUATION_FRAMEWORK.
