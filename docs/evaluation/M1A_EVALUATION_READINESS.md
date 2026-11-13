# M1a evaluation readiness (G-MATCH, G-LATEST-DATES)

Snapshot after the governance and B0-review preparation. The benchmark implementation is at
`fdb0ad2`; reports are in `reports/`.

## Verdict

**Not ready for M1a sign-off on evaluation.** Every step that can be done in code is ready or
specified. The remaining blockers need people: named roles (D19), human review of B0, expert
B1 labels and a B3 custodian. No result so far is evidence of held-out performance.

## Status by component

| Component | Status | Evidence |
|---|---|---|
| Harness, metrics, reports | Done | `backend/src/researchpilot/evaluation/`; CI green at `fdb0ad2` |
| Protocol guard (split rules, B3 refusal, aggregate-only B3) | Done; procedural limits documented | `B3_ISOLATION.md` |
| B0 datasets | 52 + 43 real cases; **all labels AI-proposed** | `backend/benchmarks/` |
| B0 results | All gates pass on AI-proposed labels | `reports/` (not a release estimate) |
| B0 review (two-stage blind) | Stage 1 (independent ground truth) and Stage 2 (expected-policy check) sheets generated for all 95 cases; **Stage 1: 0 / 95 submitted; Stage 2: 0 / 95 decided** | `review/README.md` |
| Annotation guidelines | Draft v0.1, with gaps listed | `G_MATCH_GUIDELINES.md`, `G_LATEST_DATES_GUIDELINES.md` |
| Evaluation roles (D19) | **No role assigned**; template ready | `EVALUATION_ROLES.md` |
| B1 protocol | Designed, not approved, not started | `B1_PROTOCOL.md` |
| B1 schema (ground truth separate from policy output; two annotations) | **Not implemented** (code) | `B1_PROTOCOL.md` §2 |
| Missing categories | Planned with counts and blockers | `COVERAGE_PLAN.md` |
| B3 | **Does not exist**; checklist ready; no custodian | `B3_CHECKLIST.md` |

## Findings from the B0 review preparation (for the reviewers, not label changes)

No label was changed. The review sheets flag:

1. **Truth vs policy gaps that the B0 schema hides.**
   - GD-B0-041 and GD-B0-042 expect the aggregator candidate dates (2017-06-12,
     2015-12-10). These are most likely the arXiv *submission* days. The submission times
     relative to arXiv's 14:00 US Eastern cutoff suggest announcement on 2017-06-13 and
     2015-12-14.
   - GD-B0-005/006, 040 and 043 likewise expect the policy output, not the true date.

   The labels are correct as expected-system-behaviour labels. B1 must record the true date
   separately (`B1_PROTOCOL.md` §2).
2. **Circularity risk:** GM-B0-023 was relabelled after the matcher merged the pair. It rests
   on an OpenAlex merge and a third-party re-deposit (registered by "Shenzhen Medical Academy
   of Research and Translation"). The guideline does not yet define whether such copies are
   the same work.
3. **Possible miscategorisation:** four preprint–journal pairs (GM-B0-001, 006, 007, 008)
   have different titles and may belong in `explicit_link_different_title`. This doesn't
   change any outcome.
4. **Unverified "same work" assumption:** GM-B0-024, an AIP proceedings item with the same
   title as Maldacena's paper, may be a summary rather than the paper.
5. **Development contamination:** GD-B0-034..036 drove decision 70. They stay in B0 for good.

## What is needed, in order

| # | Step | Who | Blocks |
|---|---|---|---|
| 1 | Name the evaluation lead and the B3 custodian (D19: "before M1a ends") | Project owner | M1a close |
| 2 | Review the 95 B0 cases in two blind stages (`review/README.md`): Stage 1 ground truth, then Stage 2 expected-policy decisions; rule on guideline gaps; report truth-vs-policy gaps | Team reviewer(s); evaluation lead | Trustworthy B0 regression baseline |
| 3 | Implement the B1 schema, form generator, agreement calculator and work-hash CI check | Developers (code) | B1 start |
| 4 | Approve B1 sample design and sizes; name annotators and adjudicator | Evaluation lead | B1 start |
| 5 | Pilot (20 items per benchmark), agreement check, guideline revision | Annotators, lead | Full B1 |
| 6 | Full B1 annotation, adjudication, approval, freeze | Annotators, adjudicator, lead | Calibration (D30) |
| 7 | Set up B3 storage, access, hashing, overlap check; draw and label B3 | Custodian, B3 annotators | Release decision |
| 8 | Locked B3 run on a tagged commit; aggregate report | Custodian | R1 release gate |

## B0 review process (two-stage, blind)

- **Stage 1** asks for the ground truth from primary sources (G-MATCH: relationship and
  detail; G-LATEST-DATES: true first public date, event and manifestation, or "not
  determinable"). It shows no AI label, expected behaviour, explanation, category or
  benchmark result.
- **Stage 2** reveals the AI-proposed label and expected system behaviour for a case only
  after its Stage 1 answer is submitted. That answer is then locked by fingerprint. The
  reviewer confirms, corrects, rejects the case or marks it unsure, with reasons and
  evidence.
- The generator never writes reviewer files and never changes labels. Tests cover blindness,
  the reveal order, locking and preservation.
- **Limitation:** blindness is procedural for anyone with repository access. Datasets,
  reports and earlier commits contain the labels. Reviewers should work from the Stage 1
  packet only (sheet and CSV).
- **After review:** compare Stage 1 truths with the AI-proposed expectations. This measures
  the truth-vs-policy gaps, such as GD-B0-041/042 and the submission-only cases.

## What can and cannot be claimed today

- **Can:** the harness runs the production rules from real recorded records. On 95
  development cases with AI-proposed labels, every hard gate passes. The benchmark found
  and led to a fix for one real date bug (nominal issue dates).
- **Cannot:**
  - any precision, recall or accuracy figure as an estimate of real-world or held-out
    performance;
  - that any label is human-reviewed or expert-validated;
  - that B3 exists or that release targets are met.
