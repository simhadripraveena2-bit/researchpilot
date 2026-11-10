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
| **Latest Research** | Correct windows, release types and dates; no duplicates; good recall and relevance; correct provenance | R1 |
| **Ask & Learn** | Accurate, level-appropriate, context-retaining, grounded, correctly attributed, honest when evidence is missing | R1+ |
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
| **G-LATEST-DATES** | Frozen source responses (arXiv, bioRxiv/medRxiv, Crossref, OpenAlex, S2) for ≥ 500 papers, covering: new v1 preprints (arXiv and bioRxiv/medRxiv); revisions (v2+) of old papers; journal versions of old preprints; new journal articles without preprints; older papers newly indexed (with and without OpenAlex premium filters); metadata-only updates (Crossref deposited/indexed, OpenAlex updated); **secondary-source-only dates** (OpenAlex only, S2 only); **secondary agreement without established independence** (OpenAlex and S2 agree, upstream unknown); **independently corroborated dates** (disjoint recorded upstream provenance); **all date event types** (submission, announcement/posting, revision, acceptance, online, issue, indexing, metadata); **arXiv papers with and without captured announcements**; **journal versions of existing preprints**; **conflicting dates** (authoritative vs authoritative; secondary vs secondary; secondary vs authoritative); month/year precision; future dates; **window boundaries** (timestamp exactly at start/end, 1 s either side, date-only values on boundary days); **time-zone display** cases (UTC±14, DST transitions in Europe and North America). Each labelled with true first public date, confidence, expected release type for given windows, and expected local display strings | ≥ 500 papers | team (verified against arXiv/bioRxiv abstract pages and publisher pages) | R1 |
| **G-MATCH** | Record pairs labelled same work / preprint→published / related-not-same / different: true preprint↔journal pairs (arXiv and bioRxiv/medRxiv, with and without identifier links); **adversarial similar-title pairs**: same title with different authors, generic titles, Part I/II, comment/reply/erratum/retraction, conference vs extended journal version, thesis vs article, same authors with a different paper | ≥ 600 pairs (≥ 200 adversarial) | team | R1 |
| **G-LATEST-RELEVANCE** | For 5 topics × 2 weeks: all papers in the mapped arXiv categories + other-source candidates for the window, with expert labels (relevant to objective: 0–3; sub-question) | ~5 × 2 × 300 | domain experts | R1 |
| **G-TUTOR** | Per topic: (a) concept questions at 3 levels; (b) paper-specific questions with gold answer spans; (c) equation questions with gold symbol definitions (arXiv LaTeX papers); (d) algorithm/architecture questions; (e) **unanswerable-from-paper** questions (answer not in the paper or only abstract available); (f) scripted multi-turn dialogues with follow-ups ("simpler", "example", "show the maths", pronoun references, scope switches), including **long dialogues (≥ 25 turns) whose later questions depend on facts and sources from turns 1–10** (so they are answered from the summary + carried references); (g) anchored questions (e.g. "What is message passing?" while reading a GNN paper) with the expected paper-specific meaning; (h) **progressive lessons**: per concept, expert reference points for each of the eight steps, valid check questions with answer keys, and scripted user actions (next, simpler, deeper, jump, interrupt + resume, stop) | ≥ 300 questions + 50 dialogues + 40 lessons | domain experts + educators | R1 (a,b,d,e,f,g,h) / R2 (c) |
| **G-GAPS** | Expert-rated gap candidates and ideas (real / already addressed / weak), with known prior work | ~20 per topic | senior researchers | R3 |

Annotation guidelines are written before annotation. Inter-annotator
agreement (Cohen's κ for categorical labels, Krippendorff's α for ordinal) is
reported. Labels with agreement below 0.6 are revised before use.

## 2a. Staged benchmarks and data separation

The long-term targets in §3 stay unchanged. They are reached through four
benchmark stages. **No example is used for more than one purpose**: prompt
development, threshold calibration and final evaluation each use separate
data.

| Stage | Name | Purpose | Size (initial) | Who labels | May be used for | Never used for |
|---|---|---|---|---|---|---|
| **B0** | Development benchmark | Fast iteration: prompt development, debugging, regression tests in CI | Small: 2 topics; ~50 relevance items per objective; ~100 date cases; ~100 match pairs; ~60 tutor questions + 10 dialogues + 5 lessons | Project team (non-expert labels allowed, marked as such) | Prompt writing, examples in tests, failure analysis | Calibration, release decisions |
| **B1** | Initial MVP benchmark | Calibrating thresholds (RIE tiers, matching, date rules) and the first MVP quality estimate | 3 further topics; full G-MATCH and G-LATEST-DATES calibration splits; tutor set per topic | Domain experts (2 per item) + adjudicator | Threshold/weight calibration; the "MVP estimate" reported internally | Prompt development; final release decision |
| **B2** | Expanded expert-labelled benchmark | Broader coverage before targets are claimed: more fields, levels and edge cases | 10 topics total, full gold-set sizes in §2 | Domain experts + educators (tutor) + adjudicators | Re-calibration at a release boundary; error analysis | Prompt development on the same items |
| **B3** | Held-out evaluation benchmark | Release decisions only | ≥ 2 topics (R1), growing to ≥ 4 (R2+); for Latest Research, weeks not used elsewhere; for G-MATCH and dates, a separate split | Domain experts; locked after approval | Final metrics for release gates, run by the benchmark custodian | Anything else. Developers don't see items or answers |

**Separation rules**
- Splits are made **by topic** (relevance, tutor, explanations), **by week**
  (Latest Research relevance), and **by work** (dates, matching), so the same
  paper, topic or week never appears in two stages.
- Items used in prompt examples are recorded and excluded from B1–B3
  (checked automatically by hashing the items).
- B3 is stored with restricted access. The implementing developer, including
  any AI coding assistant, never reads B3 items or answers. Evaluation runs
  on B3 are executed by the custodian and report aggregates plus
  failure categories, not item contents.
- When B3 results lead to changes, the affected B3 items are retired into B2
  and replaced, so the held-out set stays unseen.
- AI-generated labels are never gold. An LLM may pre-annotate B0 only, and
  every such label is marked and reviewed by a person.

**Targets by stage**
- **Honesty gates (§3.3) apply at every stage with zero tolerance.**
- **R1 release:** the §3 targets are evaluated on B3 (R1 size), with 95%
  confidence intervals. Because the R1 held-out set is small, a target
  counts as met if the point estimate meets it and the lower bound is no
  more than 0.05 below it. Any miss needs a documented, approved exception.
- **R2 onwards:** targets apply on the expanded B3, without the interval
  allowance.

## 2b. Labelling roles and responsibilities

| Role | Responsibility | Who (to be assigned, D19) |
|---|---|---|
| **Evaluation lead** | Owns the gold sets, writes and versions the annotation guidelines, **approves final gold answers**, signs off release evaluation reports | One named person on your side |
| **Annotators** | Label items independently, at least two per item for B1–B3; tutor items rated by a domain expert and by an annotator at the target level | Domain experts per topic; educators for level fit; team members for B0 and for date/match cases (verified against primary pages) |
| **Adjudicator** | Resolves annotator disagreements and records the reason; escalates guideline gaps to the evaluation lead | A senior domain expert per field |
| **Benchmark custodian** | Controls B3 access, runs held-out evaluations, retires and replaces exposed items | One person not involved in prompt development |
| **Developer** (including AI assistants) | Builds the harness, uses B0 freely and B1 only for calibration, never accesses B3 | Implementation team |

Process: guidelines → pilot (20 items) → agreement check (κ/α ≥ 0.6, or the
guidelines are revised) → full labelling → adjudication → evaluation-lead
approval → version freeze. Every gold item records its annotators, the
adjudicator (if any), the approver and the guideline version.

## 3. Metrics and targets

### 3.1 Discovery
- Recall@all against expert "must-include" lists per topic: **≥ 0.85**.
- Dedup precision **≥ 0.99**, recall **≥ 0.90** (G-DEDUP).
- Zero duplicate canonical papers sharing any identifier (DB constraint test).
- **Version matching (G-MATCH):** auto-match precision ≥ 0.995; recall ≥ 0.98 for pairs with decisive identifier links and ≥ 0.70 for pairs without (the rest should surface as possible matches); **0 merges of adversarial similar-title pairs**; 0 merges supported by title similarity alone (property test); 100% of merged papers keep every original source record and date claim, and a split restores them exactly.

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
- **Fabricated or mis-typed dates** on Latest Research: 0 (§3.8).
- **Fabricated equations, quotations or paper claims** in Ask & Learn: 0 (§3.9).
- **Merges supported by title similarity alone**: 0 (§3.1).
- **Secondary-only dates shown as confirmed new releases**: 0 (§3.8).
- **Conversation summaries or earlier AI answers cited as evidence**: 0 (§3.9).
- **Independent corroboration claimed without recorded provenance**: 0 (§3.8).
- **Journal versions of existing preprints presented as new research**: 0 (§3.8).
- **Full-text or equation claims beyond a paper's access level**: 0 (§3.9).
- **Inferred or hypothesised graph relationships presented as established**
  (UI, API, exports, graph-derived statements): 0 (from R2).
- **Data deleted in PostgreSQL still present in the knowledge graph** after
  reconciliation: 0 (from R2).
- **Rejected relationships re-created or re-activated** by automatic
  extraction, judgement, sync or rebuild: 0.
- **Deletion markers containing content, names, endpoint, project or user
  identifiers**: 0.

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

### 3.8 Latest Research
| Test | Metric / rule | Target |
|---|---|---|
| Window filtering | On G-LATEST-DATES, entries in *New research* for a window are exactly those whose true first public appearance (verified or corroborated, day precision or better) falls in `[start, end)` | precision = recall = 1.0 on day-precision cases; boundary cases (exact start/end, UTC vs local) pass |
| Revisions | Revised versions (vN > 1 in window, v1 before) never appear as New preprint | 0 violations |
| Metadata-only changes | Papers whose only in-window dates are metadata dates never appear in *New research* or *Updates* | 0 violations |
| Journal versions | Published versions of earlier preprints are classified as such and show the preprint date | ≥ 0.98 accuracy |
| Newly indexed | Older papers first indexed in window go to *Newly indexed* | ≥ 0.95 accuracy (depends on OpenAlex created-date availability; fallback measured separately) |
| Uncertain dates | Month/year-precision or conflicting dates go to *Date uncertain* | 1.0 |
| **Secondary-source-only dates** (D28) | A paper whose only day-precision date comes from one secondary source (`single_source`) is *Date uncertain*, never *New research*, and shows the unconfirmed date as such | 1.0 |
| **Source agreement ≠ corroboration** | Agreeing secondary sources with unknown or shared upstream provenance are `source_agreement` → *Date uncertain*; `corroborated` only when disjoint upstream provenance is recorded | 1.0; 0 corroboration claims without recorded provenance |
| Date events kept separately | Submission, announcement/posting, revision, acceptance, online publication, issue publication and metadata dates are stored and displayed as distinct events with their manifestation | 100% of G-LATEST-DATES cases |
| Submission-only arXiv dates | Without a captured announcement, the date is labelled as a submission date, with its meaning; never shown as the public release date | 100% |
| Journal versions of existing preprints | Never in *New research*, counts or the digest's new-work section; shown with the preprint's first public date | 0 violations |
| Preprint labels | All bioRxiv/medRxiv/arXiv manifestations labelled "Preprint — not peer-reviewed" unless a matched published manifestation is displayed | 100% |
| Corroborated dates | Claims with established, disjoint upstream provenance agreeing within ±1 day → allowed in a release-type tab with the corroborated badge; disagreement → *Date uncertain* | 1.0 |
| Conflicting publication dates | Primary (system-of-record) events > 2 days apart → *Date uncertain* with all events shown; a secondary claim disagreeing with a primary event is flagged but doesn't block | 1.0 |
| Window boundaries | Start inclusive, end exclusive (timestamps); 1 s before start excluded; date-only boundary days flagged; results identical whatever the user's time zone | 1.0 |
| **Local time-zone display** | Timestamps converted to the user's zone (incl. DST); date-only values never shifted; window bounds shown in local time | 100% of G-LATEST-DATES display cases |
| Latest brief completeness | Every relevant entry has all eight answers, each evidence-backed or an explicit "can't tell / not stated / none stated" | 100% |
| Opportunity grounding | Every "possible opportunity" cites an author-stated limitation/open problem/future-work sentence (or an R3 gap) | 100% |
| Challenge flags | Expert precision on cross-checked `challenges` relations | ≥ 0.80 |
| Action recommendations | Expert agreement with Read now / Save for later / Deprioritise | ≥ 0.75; changing only dates or citation counts never changes an action (property test) |
| **No fabricated dates** | Every displayed date equals a value in a stored source record of the stated type and source (automated audit over all entries) | 0 violations (release-blocking) |
| Provenance | Every entry shows source(s), date type and retrieval timestamp | 100% |
| Duplicates | Same work from several providers (incl. arXiv + DOI versions) shows once | 0 duplicate entries; dedup precision ≥ 0.99 |
| Recall | Share of expert-relevant papers (G-LATEST-RELEVANCE, label ≥ 2) present in the scan | ≥ 0.90 for arXiv-covered fields; reported per field otherwise |
| Relevance | nDCG@10 of the default Latest Research order (action, then tier) vs expert labels; Essential precision | ≥ 0.70; ≥ 0.85 |
| Recency-not-priority | Shuffling dates within the window does not change the default order or any action (property test) | must pass |
| Contribution statements | Abstract-mode contribution/method/dataset statements whose quote verifies against the abstract; "not stated" used when absent (expert check) | 100% verified; ≥ 0.9 expert agreement |
| Related-paper links | "cites" links are backed by citation records; "similar" links are labelled as similarity | 100% |
| Overlap/challenge flags | Expert agreement on a sample of flags | ≥ 0.8 precision |

### 3.9 Ask & Learn
| Test | Metric / rule | Target |
|---|---|---|
| Explanation accuracy | Expert correctness rubric (1–5) on G-TUTOR (a, b, d) | mean ≥ 4.5; no answer ≤ 2 |
| Difficulty level | Annotator at the target level rates level fit (1–5); and the same question at 3 levels is ordered correctly by independent raters | ≥ 4.0; correct ordering ≥ 0.9 |
| Follow-up context retention | Scripted dialogues: follow-ups resolve references to earlier turns and keep the anchor | ≥ 0.9 of turns |
| Anchored meaning | For anchored questions (g), the answer gives the paper-specific meaning first, citing the paper | ≥ 0.9 |
| Paper grounding | Share of paper-scope answers whose paper-specific statements are grounded in retrieved evidence | ≥ 0.95 |
| Source attribution | Cited passage actually supports the statement (expert check) | precision ≥ 0.95 |
| Uncertainty when evidence is missing | On unanswerable questions (e), the answer states "not found in sources" before any background, and gives no paper-attributed claim | ≥ 0.95; 0 fabricated paper claims |
| Background labelling | Statements not supported by project sources carry the background label | 100% (validator) + ≥ 0.95 (expert sample) |
| Mathematical explanations | Expert rubric for correctness and step clarity (G-TUTOR c, R2) | ≥ 4.5 correctness, ≥ 4.0 clarity |
| **No fabricated equations/quotes** | Paper-attributed equations match extracted equations or user selection; quotes verify | 0 violations (release-blocking) |
| Technical explanations and pseudocode | Expert rubric (correctness, completeness) | ≥ 4.3 |
| Style compliance | The requested style is followed (rater check) | ≥ 0.9 |
| Prerequisite detection | Expert agreement that listed prerequisites are needed and sufficient | ≥ 0.8 |
| Latency | Time to first streamed token | p50 ≤ 3 s, p95 ≤ 8 s |
| **Capability boundaries** | At each paper access level (metadata only, abstract only, full text processed, full text failed, equations available): no full-text claims below `full_text_processed`; no paper-equation explanation without available equation text; the required "not available in the extracted text" wording appears | 100% (validator) + ≥ 0.95 (expert sample) |
| **Progressive teaching** | On G-TUTOR (h): steps appear in order; skipped steps give a valid reason; "simpler"/"deeper"/jump/interrupt-resume behave as scripted; expert rubric per step (correctness ≥ 4.5, level fit ≥ 4.0); check answer keys correct | 100% flow correctness; rubric targets; answer keys ≥ 0.98 correct |
| **Long-context retention** | Long dialogues (f): questions depending on turns 1–10 answered correctly after summarisation | ≥ 0.9 |
| **Evidence preservation** | After summarisation, every source cited in summarised turns is still resolvable (same quote, page, section), and answers re-citing it point to the original passage | 100% |
| **Summary never evidence** | Citations pointing to a conversation summary or an earlier assistant message are rejected (adversarial suite) | 0 accepted |
| **Project memory after summarisation** | Objective, notes, saved explanations, concept progress and learning path are present in context and unchanged after summarisation and after conversation deletion | 100% |

### 3.10 UX
- Beginner task completion without help (R1 journey steps 1–8): ≥ 4 of 5
  participants.
- Post-task comprehension check (name the field's main areas, explain one
  key concept): ≥ 4 of 5.
- Expert trust survey (would rely on Essential list; found errors logged).
- Online metrics (with consent): override rate per tier, "wrong" statement
  reports per 100 cards, time to first useful paper, Latest Research
  save/dismiss rates per tier, tutor "unclear"/"wrong" rates and follow-up
  depth.
- Usability tasks for the two new features: a beginner answers "what's new
  this week that matters to me?" from Latest Research, and resolves a
  confusing term while reading using Ask & Learn, both without help (≥ 4 of
  5).

## 4. How evaluation runs

| Layer | When | How |
|---|---|---|
| Unit/property tests | every commit | deterministic signals, anti-proxy rules, validators |
| Recorded-output regression | every commit | gold inputs + recorded LLM outputs; metrics must not drop |
| Live model evaluation | nightly/weekly on B0/B1; before each release and on any provider/model/prompt change on B1 + (custodian) B3 | run agents on gold sets; compute metrics; compare to last release. A model change is evaluated per task before it is configured |
| Human evaluation | before each release | rubric sampling (≥ 50 explanations, ≥ 100 cards, all fabrication checks) |
| Online feedback | continuously | overrides, wrong-statement reports, feeds into next gold-set update |

Every evaluation run records git SHA, prompt versions, model IDs, signal
versions and weight versions, so results can be reproduced.

## 5. Calibration procedure (RIE)

1. Compute Stage A/B signals for the **B1** (and later B2) calibration items.
   B0 items are never used for calibration.
2. Fit tier thresholds (τ_high, τ_mid, τ_low, τ_rel, c_min) and evidence
   quality weights by maximising expert agreement subject to Not-useful
   precision ≥ 0.90. Matching and date thresholds (D30) are calibrated the
   same way on their B1 splits.
3. Report all metrics on **B3** (held-out), run by the custodian. Thresholds
   are versioned (`weights_version`, `match_rule_version`).
4. Re-calibrate only in a release, never silently in production.

## 6. Release gates

A release ships only if:
1. All §3.3 honesty checks pass (zero tolerance).
2. That release's metric targets are met on the **B3 held-out benchmark**
   (with the R1 interval rule in §2a), or a documented exception is approved
   by the evaluation lead.
3. No metric regresses by more than 2 points against the previous release
   without approval.
4. The usability round passes (R1, and any release that changes the main flow).
5. For any hosted deployment, gate H passes (IMPLEMENTATION_ROADMAP §8.2).

The full list of release blockers is in IMPLEMENTATION_ROADMAP §8.
