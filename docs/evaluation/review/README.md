# B0 label review: two-stage blind process

Status: **0 of 95 B0 cases reviewed** (Stage 1: 0 submitted; Stage 2: 0 decided). Every
G-MATCH (52) and G-LATEST-DATES (43) label is AI-proposed (`labels.status = ai_proposed`).
No label has been reviewed or validated by a person.

The review separates two questions that B0 labels combine:

| | Stage 1: ground truth | Stage 2: expected system behaviour |
|---|---|---|
| Question | What is true, from the primary sources? | Does the AI-proposed expectation follow from the documented guideline and the records available to the system? |
| Reviewer sees | Identifiers, primary-source URLs, original recorded records (paths, request URLs), record evidence | All of Stage 1, plus the AI-proposed label, expected behaviour, explanation, AI-cited evidence and AI notes, plus **your locked Stage 1 answer** |
| Reviewer does not see | AI-proposed label, expected behaviour, AI explanation, AI notes, case category, benchmark results | Benchmark results (not needed) |
| Answers | Truth fields (below) | `confirm` / `correct` / `reject_case` / `unsure`, with reason and evidence URLs |

The two can legitimately differ. For example, an arXiv paper whose announcement was not
captured has a true first public date (the announcement), but the system may only state the
submission. Stage 2 judges the expectation against the policy, not against the truth. The
gap is kept visible, never resolved by changing either answer.

## Files

| File | Written by | Content |
|---|---|---|
| `stage1/G_MATCH_B0_STAGE1.md`, `stage1/G_LATEST_DATES_B0_STAGE1.md` | generator | Stage 1 sheet: cases in a fixed shuffled order (IDs unchanged) |
| `stage1/g_match_b0_stage1.csv`, `stage1/g_latest_dates_b0_stage1.csv` | **reviewer** | Stage 1 answers; created blank once |
| `stage2/G_MATCH_B0_STAGE2.md`, `stage2/G_LATEST_DATES_B0_STAGE2.md` | generator | Stage 2 sheet: only cases whose Stage 1 is submitted; the others say "Locked" |
| `stage2/g_match_b0_stage2.csv`, `stage2/g_latest_dates_b0_stage2.csv` | **reviewer** | Stage 2 decisions; created blank once |
| `stage1_locks.json` | generator | SHA-256 fingerprint of each submitted Stage 1 row, recorded when its Stage 2 is revealed |

Generator: `backend/scripts/b0_review_sheets.py`. Run it after editing a CSV:
```bash
uv run python scripts/b0_review_sheets.py
```
CI runs the same with `--check`.

### Safeguards the generator enforces (tested in `tests/unit/test_review_sheets.py`)

- It **never writes an existing answer CSV** and never fills a reviewer field. New CSVs
  contain case IDs only, and no label column.
- **Stage 1 sheets contain no label information:** no outcome, confidence, basis or release
  type values, no category, no AI explanation, evidence or notes, no dataset or report paths.
  Cases are shuffled so that consecutive IDs (which share a category) are not shown together.
- A case appears in Stage 2 **only when its Stage 1 row is submitted and complete**. A
  Stage 2 answer for a case whose Stage 1 is not submitted is refused.
- When Stage 2 is revealed, the Stage 1 row is fingerprinted. If a locked Stage 1 answer
  changes later, the generator stops with an error and writes nothing.
- Unknown case IDs, unknown values, missing required fields and malformed dates are refused.
- **Labels are never changed** by the generator (see "How a reviewed label enters the
  dataset").

### What it cannot enforce (procedural)

Anyone with repository access can open the datasets (`backend/benchmarks/`), the reports
(`docs/evaluation/reports/`), Stage 2 sheets of other cases or the git history. Earlier
commits (before the two-stage process) contain a combined sheet with all labels. Blindness
therefore depends on the reviewer. The safest setup: the coordinator sends the reviewer only
the Stage 1 sheet and its CSV, and adds the reviewer's CSV back to the repository.

## Who reviews

A **team member** may review B0 (EVALUATION_FRAMEWORK §2a, §2b), but not the AI assistant
that proposed the labels. The reviewer is named by handle in both CSVs. B0 needs no expert
adjudication, and a reviewed B0 label is still not expert-validated.

## Stage 1: independent ground truth

For each case in the Stage 1 sheet:

1. Open the primary sources listed:
   - the arXiv abstract page with its submission history, and the announcement listings;
   - the bioRxiv/medRxiv page with its posting history;
   - the publisher landing page (`doi.org`).

   The recorded API responses are what the system saw. Use them as pointers, not as truth.
2. Do not run the system, open its outputs, or look at Stage 2 or the reports.
3. Fill in the row:

**G-MATCH** (`stage1/g_match_b0_stage1.csv`):

| Column | Content |
|---|---|
| `reviewer` | your handle |
| `true_relationship` | `same_work`, `related_not_same`, `different` or `cannot_determine` |
| `relationship_detail` | `preprint_and_published`, `versions_of_one_preprint`, `reprint_or_translation`, `copy_or_redeposit`, `proceedings_and_paper`, `comment_or_reply`, `correction_retraction_notice`, `component_or_supplement`, `peer_review_document`, `extension_or_follow_up`, `part_of_series`, `same_title_unrelated`, `unrelated` or `other` (explain in `notes`) |
| `evidence_urls` | primary pages you opened, space-separated |
| `notes` | optional |
| `submitted_at` | ISO date, set only when the row is final |

**G-LATEST-DATES** (`stage1/g_latest_dates_b0_stage1.csv`):

| Column | Content |
|---|---|
| `reviewer` | your handle |
| `determinable` | `yes` or **`not_determinable`** (the sources do not establish the day) |
| `true_first_public_date` | `YYYY-MM-DD`: the earliest day **any version** of the work was publicly available. Only if determinable. |
| `true_event` | `arxiv_announcement`, `arxiv_submission`, `server_posting`, `online_publication`, `issue_publication` or `other` |
| `true_manifestation` | `preprint`, `published` or `other` |
| `evidence_urls`, `notes`, `submitted_at` | as above |

4. Run the generator. Setting `submitted_at` reveals the case's Stage 2 and **locks the Stage 1
   row**. Check the row before submitting.

## Stage 2: expected-policy assessment

For each revealed case in the Stage 2 sheet:

1. Compare the AI-proposed expectation with the guideline (`../G_MATCH_GUIDELINES.md`,
   `../G_LATEST_DATES_GUIDELINES.md`) and with the records the system had (listed again on
   the sheet). Your Stage 1 truth is shown, locked, for reference.
2. Fill in the row (`stage2/*_stage2.csv`):

| Column | Content |
|---|---|
| `reviewer` | your handle |
| `decision` | `confirm`, `correct`, `reject_case` (unusable: wrong records, unverifiable) or `unsure` (needs the evaluation lead) |
| `corrected_label` | only for `correct`, in the form shown as "AI-proposed label" |
| `reason` | one or two sentences, including any truth-vs-policy gap you see |
| `evidence_urls` | pages you used |
| `review_date` | ISO date |

## How a reviewed label enters the dataset

Labels are never changed automatically. After a Stage 2 decision:

1. A person edits `backend/benchmarks/build_b0.py`:
   - `confirm`: set `labels.status` to `team_reviewed`, `annotators` to the reviewer's
     handle, and `approved_by` if the evaluation lead approves;
   - `correct`: change the expectation and explanation, then set the status as for
     `confirm`;
   - `reject_case`: remove the case. Its ID is never reused.
2. Regenerate the datasets and sheets:
   ```bash
   uv run python benchmarks/build_b0.py
   ```
   ```bash
   uv run python scripts/b0_review_sheets.py
   ```
3. Re-run the B0 benchmark. If the system now disagrees with a corrected label, that is a
   finding to report, not a reason to change the label back.
4. Commit with the reviewer named in the commit message.

The Stage 1 truths stay in the Stage 1 CSVs. B0 has no ground-truth field. Comparing the
Stage 1 truths with the AI-proposed expectations is part of the readiness report; B1 records
the truth separately (`../B1_PROTOCOL.md` §2).

## Priority order

Stage 1 is shuffled. Reviewers may still take these cases first by ID:

1. **Relabelled during preparation** (risk of circular labelling): GM-B0-012, GM-B0-023,
   GD-B0-041, GD-B0-042.
2. **Drove a rule change** (decision 70): GD-B0-034, 035, 036.
3. **Guideline gaps:** GM-B0-018, 022, 023 (copies); GM-B0-024 (proceedings); GM-B0-032
   (companion item); GM-B0-051, 052 (related vs different).
4. **Category check:** GM-B0-001, 006, 007, 008 (titles differ).
5. All remaining cases.
