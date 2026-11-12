# B1 annotation and adjudication protocol (G-MATCH, G-LATEST-DATES)

Status: **design, not started.** No B1 item, label or annotator exists. Everything here needs
the evaluation lead's approval (`EVALUATION_ROLES.md`) before annotation begins.

B1 is the calibration split (EVALUATION_FRAMEWORK §2a). It is used to calibrate matching and
date rules and thresholds (D30) and for the first internal quality estimate. It is never used
for prompt or rule development, and never for the release decision (that is B3).

## 1. Principles

1. **Two independent annotators per item.** Each labels before seeing the other's answer.
2. **Truth first, system never.** Annotators label the ground truth from primary pages. They
   do not see the system's output. System predictions, B0 reports and aggregator merges are
   never ground truth.
3. **Every disagreement is documented and adjudicated.**
4. **Agreement is measured and reported** (Cohen's κ for categorical labels, plus the
   agreement measures below). Labels with κ < 0.6 lead to a guideline revision before use
   (§2b).
5. **Full provenance:** every label records the annotator, the guideline version, the
   evidence and dates, the adjudicator, the approver and its version history.
6. **G-MATCH and G-LATEST-DATES are separate:** separate guidelines, samples, forms,
   agreement statistics and datasets. A work may appear in both, but its labels are made in
   separate sessions and never copied from one benchmark to the other.
7. **No AI labels:** an AI system may not propose, pre-fill or adjudicate B1 labels.
8. **Splits by work:** no B1 work appears in B0, B2 or B3 (`overlapping_works`, hash check
   in CI).

## 2. Schema changes needed before B1 (code, not yet done)

The B0 schema records the expected **system behaviour** (the policy output). B1 must record
the **ground truth separately**, so that truth-vs-policy gaps can be measured, not hidden.
These are small changes in `evaluation/cases.py`, the runners and the reports:

| Benchmark | Ground truth (new, from annotators) | Expected system behaviour (existing, derived) |
|---|---|---|
| G-MATCH | `true_relationship` (same_work / related_not_same / different) plus `relation_detail` (preprint→published, versions, reprint, copy, comment, erratum, retraction, extension, ...) | `outcome`, `auto_merge_allowed`, `user_confirmation_required`, `decisive_evidence` |
| G-LATEST-DATES | `true_first_public_date` (or "not determinable"), `true_first_public_event` (announced, posted, online, issue), `true_manifestation` | `first_public_date`, `basis`, `confidence`, `candidate_public_date`, release type per window |

The expected system behaviour is derived from the truth plus the evidence the system can see,
under the documented policy. This derivation is done by the evaluation lead (or a reviewed
script) after adjudication, never by running the system.

Each label also needs a per-item record:

```
annotations: [
  {annotator, guideline_version, label, evidence_urls, confidence (low/med/high),
   time_spent_min, submitted_at}
]                                      # exactly 2 for B1-B3
adjudication: {adjudicator, final_label, disagreement_type, reason, decided_at} | null
approval:     {approved_by, approved_at, dataset_version}
history:      [{version, change, by, at, reason}]
```

`guard_split` already refuses B1 labels that aren't `expert_adjudicated`. It will also check
that there are two distinct annotators and an adjudicator who is neither of them.

## 3. Process

```
sample design -> sampling -> guideline freeze -> pilot (20 items) -> agreement check
   -> (revise guidelines, repeat pilot)       -> full annotation (A and B, blind)
   -> disagreement report -> adjudication -> lead approval -> version freeze -> calibration use
```

### 3.1 Sampling (by the evaluation lead, not by developers tuning the system)

- Strata come from `COVERAGE_PLAN.md`, with fixed counts per category.
- **Candidate sources must not depend on the matcher or resolver:**
  - bioRxiv/medRxiv `/pubs` lists;
  - Crossref relation and update-to links;
  - arXiv listings (new / cross / replace);
  - title searches for same-title pairs;
  - publisher tables of contents (Part I/II, comments, errata);
  - random draws from category feeds.

  Pairs found only because the matcher proposed them would bias recall upward.
- Works are hashed and checked against B0, B2 and B3 before annotation; any overlap is
  replaced.
- Recordings for the sampled identifiers are made by someone without access to the labels
  (`run_benchmarks.py --record` is B0-only today; B1 recording needs a B1-capable recording
  path that writes outside the label files).

### 3.2 Annotation (blind, independent)

- Each annotator gets their own form (one row per item: identifiers, links to primary pages,
  the label fields, evidence URLs, confidence, notes). Forms hold **no** system output and
  **no** other annotator's labels.
- Forms are submitted to the evaluation lead (or, for B3, the custodian). Nobody sees a
  partner's form until both are in.
- Time and confidence are recorded. "Cannot determine" is a valid answer and is kept.

### 3.3 Disagreement documentation

For every item where A ≠ B (any field):

| Field | Content |
|---|---|
| item, fields that differ | e.g. `true_relationship`: same_work vs related_not_same |
| type | evidence missed / guideline unclear / guideline gap / genuinely ambiguous / clerical |
| both annotators' evidence | URLs |

The disagreement report is kept with the dataset version. It feeds guideline revisions.

### 3.4 Adjudication

- The adjudicator (neither annotator) reads both labels and the evidence, decides, and
  records the reason.
- "Guideline gap" disagreements go to the evaluation lead. The guideline is revised and
  versioned, and the affected items are re-annotated or re-adjudicated under the new version.
- Items that stay genuinely ambiguous are kept, labelled as such. For G-MATCH the expected
  system behaviour is then "possible match / user confirms". They are not dropped silently.
- The adjudicator also spot-checks 10% of agreed items.

### 3.5 Approval, freeze and versioning

- The evaluation lead approves (sets `approved_by`). The dataset gets a version
  (`b1-v1.0`). The file hash is recorded in the report.
- Any later change makes a new version with a history entry. Reports cite the version.

## 4. Agreement reporting (per benchmark, per category, pilot and full set)

| Benchmark | Measure |
|---|---|
| G-MATCH | Cohen's κ on `true_relationship` (3 classes); κ on `relation_detail`; raw agreement; confusion table A vs B |
| G-LATEST-DATES | Exact agreement on `true_first_public_date` (and within ±1 day); κ on `true_first_public_event`; κ on "determinable vs not"; distribution of date differences |
| Both | Number and share of adjudicated items by disagreement type; agreement after adjudication spot-check |

κ < 0.6 on any main field means the guideline is revised and the pilot repeated (§2b).

## 5. Sizes (proposal for the evaluation lead)

| | G-MATCH B1 | G-LATEST-DATES B1 |
|---|---|---|
| Pilot | 20 pairs | 20 cases |
| Full | 300 pairs (≥ 100 adversarial) | 250 cases |
| Per category | ≥ 15 where feasible (see COVERAGE_PLAN) | ≥ 15 where feasible |

These sizes are proposals. The framework's whole-set targets are ≥ 600 pairs (≥ 200
adversarial) and ≥ 500 papers across B1–B3.

## 6. Use of B1 by developers

Developers may read B1 to calibrate thresholds (D30) and must record each calibration run
(parameters, dataset version, results). They may not use B1 items as prompt examples or rule
fixtures. If a B1 item drives a rule change, it is recorded and moved to B0 for the next
version.

## 7. What can be done in code vs by people

| Step | Code (developers) | People |
|---|---|---|
| Schema (§2), guard checks, forms generator, agreement calculator, disagreement report, hash/overlap check | yes | — |
| Sampling design and approval | proposes tooling | evaluation lead |
| Recording source responses for sampled items | tooling | someone without label access |
| Annotation | — | two annotators |
| Adjudication | — | adjudicator |
| Approval / freeze | — | evaluation lead |
