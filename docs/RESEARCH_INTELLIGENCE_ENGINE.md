# Research Intelligence and Decision Engine

The Research Intelligence and Decision Engine (RIE) decides **what is useful
for this user's research objective, and why**. It is the core of the FILTER
stage and feeds every other stage: what to read first (LEARN), what to compare
(COMPARE), which gaps are worth investigating (INVESTIGATE), which datasets,
baselines and repositories to use (EXPERIMENT), and what to cite (PROPOSE).

Related documents: [PRODUCT_REQUIREMENTS](PRODUCT_REQUIREMENTS.md) (RIE-*
requirements), [DATABASE_SCHEMA](DATABASE_SCHEMA.md) §6 (tables),
[AGENT_DESIGN](AGENT_DESIGN.md) (Relevance Judge, Card Writer),
[EVALUATION_FRAMEWORK](EVALUATION_FRAMEWORK.md) (how it is measured).

---

## 1. Principles

1. **Usefulness is relative to an objective.** The same paper can be
   essential for "learn the field" and irrelevant for "find a gap in
   evaluation methods". Every assessment is tied to a specific, versioned
   research objective.
2. **Several kinds of usefulness, not one score.** Five dimensions are
   assessed separately and shown separately (§3).
3. **Signals first, judgement second.** Each dimension is computed from named
   signals with recorded provenance. LLM judgements are one kind of signal,
   with verified quotes. They are never the whole answer.
4. **No single proxy decides.** Publication date and citation count can never
   be the sole basis of any classification. This is enforced by rules and
   tests (§5.4).
5. **Explain or abstain.** Every recommendation answers six questions (§6).
   When the information isn't there, the engine says what is missing instead
   of guessing. "Insufficient information" is a valid outcome.
6. **The user has the last word.** Users can override any classification and
   give feedback. Overrides are never silently undone by a recompute (§8).
7. **Cheap things for everything, expensive things on demand.** Deterministic
   signals are computed for all items. LLM judgements run for a bounded top-K
   and for items the user opens. Cards are generated when viewed and then
   cached.

## 2. Inputs

### 2.1 Research objective (versioned)

The objective is created from the user's topic, level and goal by the
Planner, shown to the user in plain language, editable, and versioned. Any
edit creates a new version, and assessments are recomputed lazily against
it.

```python
class ResearchObjective(BaseModel):
    goal: Literal["learn_field", "review_literature", "find_gap",
                  "plan_experiment", "write_proposal", "track_field"]
    core_question: str                       # one sentence
    sub_questions: list[SubQuestion]         # 2–6, each with a stable key (SQ1…)
    target_tasks: list[str]                  # e.g. "molecular property prediction"
    focus_concepts: list[str]                # must-cover concepts
    exclusions: list[str]                    # out-of-scope topics/methods
    constraints: Constraints                 # compute budget, data access (open only?),
                                             # licence needs, domain, time horizon
    expertise_level: Literal["beginner", "intermediate", "advanced"]
    source: Literal["planner", "user_edit", "feedback_suggestion"]
```

### 2.2 Items that can be assessed

| Item type | Available from | Typical signal sources |
|---|---|---|
| Paper | R1 | metadata, abstract, citations, full text (R2), extractions |
| Methodology (method / architecture / algorithm) | R2 | extractions, mentions, paper relations, code links |
| Dataset | R2 | mentions, reported results, HF dataset metadata, licence |
| Benchmark (task + dataset + protocol) | R2 | reported results, protocols |
| Evaluation metric | R2 | mentions, results, extracted criticisms |
| Model | R4 | HF model metadata, reported results, licence, size |
| GitHub repository | R4 | GitHub API, link provenance, README |
| Research gap | R3 | gap signals, overlap/contradiction probes |
| Research idea / hypothesis | R3 | novelty checks, red-team reviews, feasibility signals |

All of these are rows in a shared `research_items` table, so assessments,
overrides, feedback and notes use one mechanism (see DATABASE_SCHEMA §2).

## 3. The five usefulness dimensions

| Dimension | Question it answers | Not the same as |
|---|---|---|
| **Foundational importance** | Is this something the field builds on, so the user needs to know it? | "Highly cited" |
| **Direct relevance** | Does it address the objective's core question or sub-questions? | "Same keywords" |
| **Methodological usefulness** | Can the user learn, adopt, adapt or compare against its method? | "Proposes a method" |
| **Experimental usefulness** | Does it provide datasets, benchmarks, baselines, protocols, code or results the user can use in experiments? | "Has experiments" |
| **Novelty implications** | How does it affect the novelty of the user's gaps or ideas (closest prior work, already addresses it, supports it, contradicts it)? | "Is new" |

Two further attributes are shown but are not usefulness dimensions:

- **Currency:** how recent the item is relative to the field's pace. Used only
  for the "Latest" view and the `track_field` goal, and never on its own to
  decide priority.
- **Accessibility:** for papers, whether full text is available and whether
  it's a survey or tutorial. For resources, licence and availability. This
  matters most for beginners and for experiment feasibility.

Novelty implications only exist once the project has gaps or ideas (R3).
Before that, the dimension shows "Not assessed yet — no ideas or gaps in this
project".

## 4. Signals

A **signal** is one measurable piece of evidence about an item for one
dimension.

```python
class Signal(BaseModel):
    key: str                 # e.g. "paper.in_corpus_citation_share"
    family: SignalFamily     # semantic_match | citation_structure | content_extraction |
                             # resource_availability | llm_judgement | user | currency
    dimension: Dimension
    value: float | None      # normalised 0–1; None = not available
    raw: dict                # the underlying numbers
    method: Literal["deterministic", "llm_judgement", "external_metadata", "user"]
    evidence: list[EvidenceRef]   # papers, spans, source records
    computed_at: datetime
    version: str             # signal implementation version
```

Signals are implemented as small plugins registered per (item type,
dimension). Adding a signal doesn't change the engine.

### 4.1 Signal catalogue (initial)

**Papers**

| Dimension | Signal | Method | Release |
|---|---|---|---|
| Foundational | Share of project papers that cite it (in-corpus citation share) | deterministic | R1 |
| Foundational | Co-citation centrality in the project graph | deterministic | R1 |
| Foundational | Field-normalised citation percentile (relative to papers of the same field and year, from OpenAlex/S2) — **capped weight** | external metadata | R1 |
| Foundational | Cited with a "background"/"methodology" intent by project papers (S2 citation intents) | external metadata | R1 |
| Foundational | Originates a method or concept used by ≥ k project papers | deterministic over extractions | R2 |
| Foundational | Is a survey or tutorial covering the topic (accessibility for learners) | deterministic + metadata | R1 |
| Direct relevance | Semantic similarity of title+abstract to the core question and to each sub-question | deterministic (embeddings) | R1 |
| Direct relevance | Coverage of focus concepts; hits on exclusions (negative) | deterministic | R1 |
| Direct relevance | Task match: the paper's tasks match the objective's target tasks | deterministic over extractions | R2 |
| Direct relevance | **Relevance judgement**: direct / partial / tangential / not relevant, per sub-question, with a verified quote | LLM | R1 (top-K) |
| Methodological | Proposes or substantially extends a method in the objective's method space | extraction | R2 |
| Methodological | Method described in enough detail (algorithm/equations/hyperparameters present) | extraction | R2 |
| Methodological | Number of project papers that build on it (`improves_on`/`extends` relations) | deterministic | R2 |
| Methodological | Official implementation available | link resolution | R4 (R1: links in abstract/metadata only) |
| Experimental | Reports results on datasets/benchmarks relevant to the target tasks | extraction | R2 |
| Experimental | Protocol completeness (splits, baselines, hyperparameters, compute reported) | extraction | R2 |
| Experimental | Compute requirements compatible with the user's constraints (only from reported compute) | extraction | R2 |
| Novelty | Similarity to each user gap/idea; overlap judgement with quote (addresses / partially addresses / supports / contradicts) | deterministic + LLM | R3 |
| Currency | Months since first publication relative to the direction's median | deterministic | R1 |

**Datasets / benchmarks**: usage count in project papers and in papers on the
target task; task match; licence (from HF/metadata, never inferred by an LLM);
availability (download location exists); size and modalities; documented
limitations (extracted from papers or dataset cards); saturation (top reported
results near the metric ceiling, computed only from extracted results); split
standardisation across papers.

**Metrics**: frequency of use for the target task; consistency of definition
across papers; extracted criticisms or known failure modes; whether it
measures what the objective's sub-questions ask about (LLM judgement with
quote).

**Methodologies**: adoption count, recency of improvements, reported
performance range on target benchmarks, assumptions (extracted), code
availability, compute profile.

**Models**: task match, licence, parameter count vs. compute constraint,
availability (HF), reported results with provenance, model-card limitations.

**Repositories**: link confidence (URL in paper > HF paper page > README
mentions paper > name search), official vs. third-party, licence, last
activity, archived flag, presence of dependency files and instructions,
stars as a **weak, capped** popularity signal.

**Gaps**: recurrence across independent groups, sparsity signal strength,
overlap-probe outcome, contradiction-probe outcome, evidence count and
quality.

**Ideas / hypotheses**: novelty-check outcome, red-team verdict and
unresolved objections, feasibility signals (datasets available, compute,
code), significance rationale, evidence for and against.

## 5. Scoring

### 5.1 Dimension scores

For an item `i`, objective `o` and dimension `d`, with available signals `S`
and configured weights `w_s`:

```
score(i,o,d)    = Σ_{s∈S, value≠None} w_s · v_s  /  Σ_{s∈S, value≠None} w_s
coverage(i,o,d) = Σ_{s∈S, value≠None} w_s  /  Σ_{s∈S} w_s
confidence(i,o,d) = coverage × mean(evidence_quality_s)
```

`evidence_quality` is 1.0 for a quote-verified span or a deterministic count,
0.8 for external metadata, 0.7 for an LLM judgement with a verified quote, and
0.3 for an LLM judgement without full text (abstract only). The values are
configurable and calibrated (EVALUATION_FRAMEWORK §5).

If `coverage < 0.4`, the dimension is reported as **"insufficient
information"**, together with the missing signals.

### 5.2 Objective profiles

Each goal has a default weighting over dimensions. Users never see these
weights unless they open "How was this ranked?". The profile is versioned and
can be adjusted (§8.3).

| Goal | Foundational | Direct | Methodological | Experimental | Novelty |
|---|---|---|---|---|---|
| learn_field | 0.35 | 0.35 | 0.15 | 0.05 | 0.10 |
| review_literature | 0.20 | 0.45 | 0.20 | 0.10 | 0.05 |
| find_gap | 0.10 | 0.30 | 0.20 | 0.10 | 0.30 |
| plan_experiment | 0.05 | 0.25 | 0.25 | 0.40 | 0.05 |
| write_proposal | 0.15 | 0.30 | 0.15 | 0.15 | 0.25 |
| track_field | 0.05 | 0.50 | 0.20 | 0.15 | 0.10 (+ currency used for ordering) |

Weights are renormalised over dimensions that have enough coverage.

### 5.3 Priority tiers

The UI shows tiers rather than raw numbers.

| Tier | Rule (thresholds calibrated on gold sets) |
|---|---|
| **Essential** | priority ≥ τ_high **and** direct relevance ≥ τ_rel **and** signals from ≥ 2 families, at least one content-based (semantic match, content extraction or verified LLM judgement) **and** confidence ≥ c_min |
| **Recommended** | priority ≥ τ_mid, and the same family rule |
| **Optional** | relevant but low priority for this goal |
| **Not useful for this objective** | direct relevance < τ_low with adequate coverage, or matches an exclusion. Always states the reason |
| **Insufficient information** | coverage too low to decide. Lists what's missing and how to get it |

Alongside the tier, an item gets zero or more **role tags** that explain how
it is useful: *Foundational*, *Directly relevant*, *Method source*,
*Baseline*, *Evaluation resource*, *Learning resource*, *Closest prior work*,
*Supports gap*, *Challenges idea*.

### 5.4 Anti-proxy rules (enforced)

- Citation-derived signals together may contribute at most **30%** of the
  foundational dimension and **10%** of any other dimension.
- Currency signals contribute **0%** to the five usefulness dimensions. They
  are used only to order the "Latest" view and in the `track_field` goal.
- An item cannot reach Essential or Recommended from citation and currency
  signals alone (the family rule in §5.3).
- Repository stars contribute at most 10% of experimental usefulness.
- A property-based test generates items whose only non-null signals are
  citation and date signals and asserts that they never reach Essential or
  Recommended. Another test asserts that ranking changes when content signals
  change while citations stay fixed.

### 5.5 Two-stage computation and cost control

1. **Stage A (all items, deterministic):** compute non-LLM signals and a
   prescore. This is cheap and runs after every discovery or analysis
   update.
2. **Stage B (top-K + opened items):** run LLM relevance judgements for the
   top-K by prescore (default K = 150 papers), plus any item the user opens,
   pins or overrides. Items outside top-K show their Stage-A tier with the
   note "Quick assessment — open for a detailed one".
3. **Cards** (§6) are generated when an item is viewed and cached by
   `(item, objective_version, signals_hash, prompt_version)`.

## 6. The recommendation card

Every recommendation, whatever the item type, answers the same six
questions.

```python
class RecommendationCard(BaseModel):
    item_id: UUID
    objective_version: int
    tier: Tier
    role_tags: list[RoleTag]
    why_relevant: list[Statement]          # 1. relevance to the objective / sub-questions
    use_for: list[UseCase]                 # 2. what it can be used for
    strengths: list[Statement]             # 3.
    limitations: list[Statement]           # 4.
    priority: PriorityExplanation          # 5. worth prioritising? tier + reasons + comparison
    missing_information: list[MissingInfo] # 6.
    dimensions: dict[Dimension, DimensionSummary]  # score band, confidence, top signals
    level: Literal["beginner", "intermediate", "advanced"]

class Statement(BaseModel):
    text: str
    kind: ClaimKind                # reported_finding | extracted_observation |
                                   # ai_interpretation | unverified_hypothesis
    grounding: Literal["grounded", "background"] | None
    evidence: list[EvidenceRef]    # spans, papers, signals
    signal_keys: list[str]

class UseCase(BaseModel):
    use: Literal["learn_background", "cite_as_foundation", "adopt_method",
                 "compare_against", "use_as_baseline", "evaluate_on",
                 "measure_with", "reuse_code", "position_novelty_against",
                 "avoid_or_treat_with_caution"]
    stage: JourneyStage            # where in the journey it applies
    sub_question_keys: list[str]
    explanation: Statement

class MissingInfo(BaseModel):
    what: str                      # e.g. "Full text", "Dataset licence", "Compute used"
    why_it_matters: str
    how_to_get: str | None         # e.g. "Upload the PDF", "Check the dataset card"
    blocks_dimensions: list[Dimension]
```

**How a card is built:**

1. **Deterministic skeleton:** tier, role tags, dimension summaries and
   missing information come straight from signals and coverage. Signal
   statements become `extracted_observation`s (e.g. "Cited by 14 of the 120
   papers in this project").
2. **Evidence statements:** author-stated limitations and reported results
   come from extractions as `reported_finding`s, with quotes.
3. **Card Writer (LLM):** phrases "why relevant", "use for" and the priority
   explanation at the user's level, using only the skeleton and evidence
   given to it. Its output is `ai_interpretation` (grounded), and every
   statement must reference given evidence or signals.
4. **Validation:** the claim validator checks references, quotes, numbers and
   kinds. A card must have at least one strength and one limitation, or an
   explicit "none found in the available text" entry plus a matching
   missing-information item.

Beginner cards use plain language, two or three statements per field, and
glossary links. Advanced cards add signal values, sub-question coverage and
comparisons with neighbouring items.

## 7. Verification of claims and classifications

### 7.1 Claim verification levels

Every `Statement`/claim records how it was verified (`claim_verifications`
table):

| Level | Applies to | Check |
|---|---|---|
| `quote_verified` | reported findings, grounded interpretations quoting text | Quote found in stored text after normalisation. Page/section recorded |
| `data_derived` | extracted observations | Recomputing from the referenced rows gives the same value |
| `metadata_confirmed` | licences, dates, stars, venue | Value present in a stored source record; cross-source agreement noted |
| `cross_checked` | high-stakes LLM judgements (below) | Two independent judgements agree |
| `unverified` | hypotheses, background explanations | Labelled as such; never shown as fact |

### 7.2 Verifying classifications

- **Deterministic signals:** unit tests, versioned implementations, and a
  recompute check (the same inputs must give the same output).
- **LLM judgements:** structured output, enum-constrained labels, a mandatory
  quote that must verify, and IDs that must exist in the project.
- **High-stakes judgements are cross-checked:** "not relevant" for an item the
  prescore ranked highly, "already addressed" for a gap, "closest prior work"
  for an idea, any Essential tier from abstract-only evidence, and any
  `challenges` relation on a Latest brief. A second
  judgement runs with a differently phrased prompt and the evidence in a
  different order. Disagreement gives the label "uncertain", lowers
  confidence and shows both views.
- **Factual attributes are never inferred by the LLM:** licences, star counts,
  dataset sizes and dates come from metadata or are reported as missing.
  Whether code is "official" requires the URL in the paper text or the
  Hugging Face paper page.
- **Counter-evidence:** for statements that drive priority ("standard
  baseline", "widely used benchmark", "state of the art on X"), the engine
  checks the project record for contradicting evidence (other results,
  criticisms). If any is found, it's shown next to the statement.
- **Audit trail:** each assessment stores signal values, weights version,
  prompt versions and model IDs. "How was this ranked?" renders it.
- **Calibration:** tier thresholds and evidence-quality weights are fitted on
  gold sets (EVALUATION_FRAMEWORK). A release is blocked if calibration
  drifts.

## 8. User overrides and feedback

### 8.1 Overrides

Users can override any of: tier, role tags, any dimension classification
(e.g. "this *is* foundational"), sub-question relevance, use cases, and
inclusion/exclusion. Each override:

- stores the system value, the user value, an optional reason (free text or a
  quick-pick such as "wrong topic", "too basic", "already known", "low
  quality", "important for me") and a timestamp;
- takes precedence in every view and export, shown as "Your classification
  (system suggested: Optional)";
- survives recomputes. If new evidence would change the system's value, the
  user sees a non-blocking note ("New evidence suggests Essential — keep your
  classification?");
- is written to the project decision log.

### 8.2 Feedback

- Card-level: helpful / not helpful.
- Statement-level: "this is wrong" (the statement is hidden pending
  re-verification and the case is logged for evaluation) and "unclear".
- Missing-item feedback: "you missed X". The user adds the item by ID, it is
  assessed, and the case is recorded as a recall failure.

### 8.3 How feedback changes behaviour (bounded and visible)

1. **Objective refinement suggestions:** patterns in overrides (e.g. six
   papers about topic Y marked "wrong topic") produce a suggested objective
   edit ("Add Y to exclusions?"). Nothing changes until the user accepts.
2. **Per-project weight adaptation:** after at least 20 overrides, the engine
   fits a bounded adjustment of the objective profile weights (each weight
   may move by at most ±50% of its default). The change is shown ("Methods
   now count more, based on your choices") with one-click undo.
3. **No silent global learning:** feedback feeds evaluation datasets
   (anonymised, opt-in), not automatic model or prompt changes. Prompt and
   weight updates ship as versioned releases that have been evaluated.

## 9. Recompute and staleness

Assessments are keyed by `(item, objective_version, signals_hash,
weights_version)`. Domain events (`paper.added`, `document.parsed`,
`extraction.completed`, `objective.updated`, `gap.updated`,
`override.created`) mark affected assessments stale. Stage A recomputes
right away; Stage B and cards are recomputed when next viewed. Cards show "Updated
since you last saw it" when the tier changes.

## 10. Recent items (Latest Research) and tutor support

### 10.1 Assessing very recent papers
Papers from the last days have no citation history. The RIE handles them
without special-casing the scoring:

- **Foundational importance** is reported as **"Too recent to judge
  influence"** for items whose first public date is under 90 days old. Its
  citation-structure signals are null, the dimension's coverage falls below
  the threshold, and the objective profile is renormalised over the
  remaining dimensions (§5.2). Content signals (e.g. "introduces a method
  that addresses SQ2") still count.
- **Recency is never a priority signal** on the Latest Research page. The
  date window is a filter, and the default order (action, then tier) uses the same objective
  profile as everywhere else (anti-proxy rules §5.4 unchanged).
- **Novelty implications from R1:** before gaps and ideas exist (R3), this
  dimension is assessed against the project's **current direction**: the
  objective plus the user's Essential/saved items. The Relevance Judge
  returns `relation_to_project ∈ {extends, alternative_to, challenges,
  overlaps_with, unrelated}` with the project item it relates to and a
  verified quote from the new paper's abstract. From R3, the same signal is
  also computed against open gaps and accepted ideas.

### 10.2 The Latest brief (eight questions) and card additions

`RecommendationCard` gains two optional fields, used on the Latest Research
page and anywhere a recent item appears:

```python
    whats_new: list[Statement] | None        # what changes compared with earlier work
    relation_to_project: list[ProjectRelation] | None
                                             # {relation, project_item_id, evidence, kind}
```

For every relevant new paper (Stage B top-K, or any entry the user opens),
the engine assembles a **Latest brief** from the same evidence pipeline. The
brief adds no new judgement machinery. Each question maps to an existing
mechanism:

| # | Question | Source of the answer | Claim kind | If no evidence |
|---|---|---|---|---|
| 1 | What is the paper about? | Card Writer from the abstract (and full text if parsed) | `ai_interpretation` (grounded, quotes the abstract) | — (an abstract is required; without one: "No abstract available") |
| 2 | What is new compared with earlier work? | (a) the paper's own comparative statements ("outperforms X", "unlike prior work…") from Extractor abstract mode; (b) comparison with named project items via `relation_to_project` | (a) `reported_finding` with quote; (b) `ai_interpretation` grounded in both items | "Can't tell from the abstract" |
| 3 | What method, dataset or benchmark does it introduce? | Extractor abstract mode (full text in R2) | `reported_finding` with quote | "Not stated in the abstract" + missing info "Full text needed" |
| 4 | How does it relate to the research objective? | Relevance Judge per sub-question + tier | `ai_interpretation` (grounded) + `extracted_observation` (tier, sub-questions) | "Insufficient information" tier |
| 5 | Does it overlap with saved papers? | Related Item Linker (`cites` from citation data; `similar` from text similarity) + `relation_to_project = overlaps_with` | `extracted_observation` (links) + `ai_interpretation` (overlap judgement, quotes both) | "No overlap found with your saved papers" (stating what was compared) |
| 6 | Does it challenge existing assumptions or the user's proposals? | `relation_to_project = challenges`, against saved/Essential items and the objective (R1); against open gaps, accepted ideas and extracted assumptions (R2–R3). **High-stakes, so cross-checked** | `ai_interpretation` quoting the new paper **and** the challenged item | "No challenge detected" (with scope of the check) |
| 7 | Does it suggest a research opportunity? | Only from an author-stated limitation, open problem or future work in the paper's text, or (R3) a match with an open project gap | `unverified_hypothesis`, citing the source sentence | Omitted ("None stated") — never invented |
| 8 | Read now, save for later, or deprioritise? | Deterministic action rule (below) | `extracted_observation` with reasons | "Check manually" when the tier is Insufficient information |

**Action rule** (deterministic, versioned, overridable):

| Action | Condition |
|---|---|
| **Read now** | Tier Essential, **or** a cross-checked `challenges` relation to an Essential/saved item or an accepted idea, **or** tier Recommended with direct relevance to a sub-question the user marked as priority |
| **Save for later** | Tier Recommended (otherwise), or Optional with a `cites`/`overlaps_with` link to saved items |
| **Deprioritise** | Tier Optional without links, or Not useful for this objective (reason shown) |
| **Check manually** | Tier Insufficient information (missing information listed) |

The action never uses the date, the date's confidence or the citation
count. A property test asserts that changing only dates leaves every action
unchanged. The user can change the action, and that is stored as an
override (§8) and logged.

"What you could learn from it" is expressed through `use_for` with the
`learn_background` and `adopt_method` uses, tied to sub-questions.

### 10.3 Signals added
| Item | Dimension | Signal | Method | Rel. |
|---|---|---|---|---|
| Paper | Novelty implications | `relation_to_project` (vs. objective + saved/Essential items) | LLM judgement with quote | R1 |
| Paper | Direct relevance | Sub-question match from scan query provenance (which subtopic's query found it) | deterministic | R1 |
| Paper | Direct relevance | Similarity to the user's saved/Essential items | deterministic | R1 |
| Paper | — (display only) | `cites_saved_items` (count and IDs) | deterministic (citations when available) | R1 |
| Paper | Novelty implications | Author-stated limitation / open problem / future work in the abstract (feeds brief question 7) | Extractor abstract mode, quote-verified | R1 |

### 10.4 Support for Ask & Learn
- When the tutor suggests further reading or prerequisites, it picks
  project items tagged **Learning resource** or **Foundational** for the
  current objective, and shows the tier.
- Saving a tutor answer about an item doesn't change the item's
  assessment. Notes are not signals, so the user's notes never feed back into
  rankings without an explicit override.

## 11. Example (abbreviated, synthetic)

The paper, numbers and quotes below are **placeholders** that show the
format. They are not claims about any real paper.

Objective: *find_gap*, "test-time adaptation for vision models under
natural (non-synthetic) distribution shift", advanced.

> **Paper P17: "<title of an early test-time adaptation method>"** —
> *Essential* · Foundational · Method source · Closest prior work (Idea H2)
>
> **Why relevant** — Introduces the adaptation approach that N of the 84
> project papers build on *(Extracted)*. Directly addresses SQ1 "how do
> models adapt without labels at test time" *(AI explanation, quoting the
> abstract)*.
>
> **Use for** — Baseline for EXPERIMENT; closest prior work to position Idea
> H2 against in PROPOSE.
>
> **Strengths** — Reports results on <benchmark A> and <benchmark B>
> *(Reported, page/section from the stored span)*; official code linked in
> the paper *(Extracted)*.
>
> **Limitations** — All reported datasets are synthetic-corruption benchmarks
> *(Extracted from reported datasets)*; "<author-stated limitation quote>"
> *(Reported, §5)*.
>
> **Worth prioritising?** Yes — required baseline, and the main comparison
> point for your idea.
>
> **Missing information** — No results on natural-shift benchmarks in this
> paper; 3 later project papers report them.
