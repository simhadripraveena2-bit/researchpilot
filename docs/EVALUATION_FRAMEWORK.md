# Evaluation Framework

How we know ResearchPilot's outputs are correct, useful and honest, and the
gates each release must pass.

## 1. What is evaluated

| Area | Question | Release |
|---|---|---|
| Discovery & dedup | Do we find the right papers once each? | R1 |
| **Research Intelligence Engine** | Do tiers and dimensions match expert judgement for the objective, and beat date/citation-only ranking? | R1+ |
| Verification | Are quotes, citations and numbers real? | R1+ |
| Explanations | Are they correct, grounded, level-appropriate and clear? | R1+ |
| Field map & learning path | Do experts agree with the structure and ordering? | R1 |
| Extraction | Precision/recall of datasets, metrics, results, limitations, etc. | R2 |
| Comparison & conflicts | Are relations and conflicts correct and comparable? | R2 |
| Gaps & ideas | Are gaps real, probes adequate, ideas defensible? | R3 |
| Experiment resources | Are baselines, datasets, metrics and compute statements correct? | R4 |
| UX | Can beginners complete the journey; do experts trust it? | R1+ |

## 2. Gold datasets

All gold sets are versioned in `backend/tests/eval/` (small) or an evaluation
data store (larger). They record annotator, date and guidelines version.

| Set | Contents | Size target | Annotators | Release |
|---|---|---|---|---|
| **G-TOPICS** | Reference topics spanning ML, biomedicine, physics, social science, HCI, each with a written objective for 2–3 goals | 10 topics × 2–3 objectives | project team + domain volunteers | R1 |
| **G-DEDUP** | Record pairs labelled same/different work, incl. preprint ↔ published | ≥ 500 pairs | team | R1 |
| **G-RELEVANCE** | Per topic-objective: ~100 candidate papers, each labelled with graded relevance (0–3) per sub-question, a tier, and dimension labels (foundational, methodological, experimental: yes/partly/no) | ≥ 2,000 judgements | ≥ 2 domain experts per topic; disagreements adjudicated | R1 |
| **G-RESOURCES** | Datasets, metrics, baselines, repos per topic, with expert tiers and usefulness notes | ~30 per topic | experts | R2/R4 |
| **G-EXTRACT** | OA papers with hand-labelled datasets, metrics, results tuples, limitations, assumptions, protocols, compute | ≥ 40 papers | team | R2 |
| **G-EXPLAIN** | Subjects (sections, equations, concepts) with reference points to cover per level | ~150 subjects × 3 levels | domain experts + educators | R1/R2 |
| **G-STRUCTURE** | Expert field outlines and prerequisite orderings per topic | per topic | experts | R1 |
| **G-GAPS** | Expert-rated gap candidates and ideas (real / already addressed / weak), with known prior work | ~20 per topic | senior researchers | R3 |

Annotation guidelines are written before annotation. Inter-annotator
agreement (Cohen's κ for categorical labels, Krippendorff's α for ordinal) is
reported. Labels with agreement below 0.6 are revised before use.

## 3. Metrics and targets

### 3.1 Discovery
- Recall@all against expert "must-include" lists per topic: **≥ 0.85**.
- Dedup precision **≥ 0.99**, recall **≥ 0.90** (G-DEDUP).
- Zero duplicate canonical papers sharing any identifier (DB constraint test).

### 3.2 Research Intelligence Engine
| Metric | Definition | Target (R1) |
|---|---|---|
| nDCG@20 (per objective) | Ranking by RIE priority vs. graded expert relevance | ≥ 0.70 |
| **Beat-the-proxy** | nDCG@20 of RIE minus that of (a) citation-count ranking, (b) recency ranking, (c) embedding similarity only | > 0 on every topic, mean ≥ +0.10 vs. (a) and (b) |
| Essential precision | Share of system "Essential" items experts rate tier ≥ Recommended | ≥ 0.85 |
| Not-useful precision | Share of "Not useful" items experts also rate not useful | ≥ 0.90 (wrongly hiding is costly) |
| Dimension agreement | κ between system and expert labels for foundational / methodological / experimental | ≥ 0.5 (R1, abstract-level), ≥ 0.6 (R2, full text) |
| Calibration | Expected calibration error of confidence vs. expert agreement | ≤ 0.10 |
| Insufficient-information honesty | Share of items marked insufficient where experts also say "can't judge from available info" | tracked; no target in R1 |
| Card completeness | Cards with all six fields (or an explicit "none found" + missing-info entry) | 100% |
| Card statement support | Statements whose evidence verifies (quote, data or metadata) | 100% for Reported/Extracted; ≥ 95% grounded AI statements referencing valid evidence |
| Anti-proxy rule tests | Property tests from RIE §5.4 | must pass |

### 3.3 Verification and honesty (all releases, release-blocking)
- **Fabricated citations:** 0 in audits (every rendered citation resolves to a stored paper record).
- **Unverified quotes shown as verified:** 0.
- **Numbers in reports/cards not traceable** to `reported_results`, metadata or computed statistics: 0.
- **Background explanations containing paper-specific claims:** 0 in the adversarial validator suite.
- **Banned novelty phrasings** ("novel", "first ever", "guaranteed") in idea outputs: 0, by automated scan.

### 3.4 Explanations
Human rubric (1–5) per explanation, rated by an annotator at the target level
plus a domain expert:
- **Correctness** (expert) — target mean ≥ 4.5, no score ≤ 2 on G-EXPLAIN.
- **Grounding** (expert) — grounded statements match the source — ≥ 4.5.
- **Level fit** (annotator at that level) — ≥ 4.0.
- **Clarity** (annotator) — ≥ 4.0.
- **Level separation:** readability and term density differ in the
  expected direction between levels (automatic check, supporting signal only).

LLM-as-judge may pre-screen at scale, but only after its agreement with human
raters is measured (≥ 0.7 Spearman on a held-out subset). It is never the
sole gate.

### 3.5 Field map and learning path
- Expert rating of direction coherence and labels (1–5): mean ≥ 4.0.
- Adjusted mutual information with expert outlines (G-STRUCTURE): tracked.
- Learning path: no item placed before its recorded prerequisite (automatic);
  expert ordering acceptability ≥ 4.0/5.

### 3.6 Extraction (R2)
Dataset mentions P ≥ 0.90 / R ≥ 0.75; results tuples P ≥ 0.90; limitations
P ≥ 0.85; assumptions P ≥ 0.80; compute reports P ≥ 0.90; quote verification
rate ≥ 0.95 of raw outputs.

### 3.7 Gaps and ideas (R3)
- Gap reality (expert: real and open, or partially open): ≥ 0.6 of surfaced
  gaps.
- Probe adequacy: for gaps experts know are already addressed, the system
  finds the addressing work in ≥ 0.7 of cases.
- Red-team usefulness (expert 1–5): ≥ 3.5; at least one substantive objection
  per idea.

### 3.8 UX
- Beginner task completion without help (R1 journey steps 1–8): ≥ 4 of 5
  participants.
- Post-task comprehension check (name the field's main areas, explain one
  key concept): ≥ 4 of 5.
- Expert trust survey (would rely on Essential list; found errors logged).
- Online metrics (with consent): override rate per tier, "wrong" statement
  reports per 100 cards, time to first useful paper.

## 4. How evaluation runs

| Layer | When | How |
|---|---|---|
| Unit/property tests | every commit | deterministic signals, anti-proxy rules, validators |
| Recorded-output regression | every commit | gold inputs + recorded LLM outputs; metrics must not drop |
| Live model evaluation | nightly/weekly + before each release + on any prompt/model change | run agents on gold sets; compute metrics; compare to last release |
| Human evaluation | before each release | rubric sampling (≥ 50 explanations, ≥ 100 cards, all fabrication checks) |
| Online feedback | continuously | overrides, wrong-statement reports, feeds into next gold-set update |

Every evaluation run records git SHA, prompt versions, model IDs, signal
versions and weight versions, so results can be reproduced.

## 5. Calibration procedure (RIE)

1. Compute Stage A/B signals for G-RELEVANCE items.
2. Fit tier thresholds (τ_high, τ_mid, τ_low, τ_rel, c_min) and evidence
   quality weights on a training split (topics A–F) by maximising expert
   agreement subject to Not-useful precision ≥ 0.90.
3. Report all metrics on held-out topics (G–J). Thresholds are versioned
   (`weights_version`).
4. Re-calibrate only in a release, never silently in production.

## 6. Release gates

A release ships only if:
1. All §3.3 honesty checks pass (zero tolerance).
2. That release's metric targets are met on held-out topics, or a documented
   exception is approved.
3. No metric regresses by more than 2 points against the previous release
   without approval.
4. The usability round passes (R1, and any release that changes the main flow).
