# Evaluation roles: assignment template (D19)

**Status: no role is assigned.** Decision D19 (IMPLEMENTATION_ROADMAP §7.3) is still open. It
says the evaluation lead and custodian are needed "before M1a ends" and annotators "before
M1b calibration". This template lists what each role does and may access. The project owner
fills in the names; nobody named here may be an AI system.

Source of the roles: EVALUATION_FRAMEWORK §2a (separation rules) and §2b (roles and process).
The scope here is G-MATCH and G-LATEST-DATES (M1a). Relevance, tutor and explanation sets get
their own annotators later (domain experts and educators).

## Assignment record

| Role | Person (name / handle) | Organisation | Assigned by | Date | Conflicts declared | Accepted |
|---|---|---|---|---|---|---|
| Evaluation lead | _unassigned_ | | | | | |
| Annotator A (G-MATCH) | _unassigned_ | | | | | |
| Annotator B (G-MATCH) | _unassigned_ | | | | | |
| Annotator A (G-LATEST-DATES) | _unassigned_ | | | | | |
| Annotator B (G-LATEST-DATES) | _unassigned_ | | | | | |
| Adjudicator | _unassigned_ | | | | | |
| B3 custodian | _unassigned_ | | | | | |
| Deputy custodian (optional) | _unassigned_ | | | | | |

The same person may annotate both benchmarks. The constraints below still apply.

## Incompatible combinations

| Combination | Allowed? | Why |
|---|---|---|
| Custodian + developer (incl. anyone prompting an AI coding assistant on this repository) | **No** | The custodian holds B3; developers must never see it (§2a) |
| Custodian + annotator of B0/B1/B2 | Yes, if they annotate no B3 items they hold | Keeps the custodian independent of tuning data |
| B3 annotator + developer | **No** | B3 answers would reach the developers |
| Annotator A + annotator B on the same item | **No** | Two independent labels are required |
| Adjudicator + annotator of the same item | **No** | The adjudicator resolves disagreements they were not part of |
| Evaluation lead + adjudicator | Possible, but not recommended | The lead approves adjudicated answers; doing both removes a check |
| Evaluation lead + developer | Possible for B0–B2; **never** with B3 access | The lead sees B3 aggregates only, like everyone else |
| Any role + AI system | **No** | AI labels are never gold; AI may pre-annotate B0 only, marked and reviewed by a person |

## Evaluation lead

**Responsibilities:**
- Owns the gold sets and the guidelines (`G_MATCH_GUIDELINES.md`,
  `G_LATEST_DATES_GUIDELINES.md`), versions them and resolves guideline gaps the adjudicator
  escalates.
- Approves the final B1–B3 labels (sets `approved_by`) and freezes each version.
- Approves the sample design and sizes for B1–B3 (see `B1_PROTOCOL.md`, `COVERAGE_PLAN.md`).
- Signs off agreement reports; decides when κ/α < 0.6 means a guideline revision.
- Signs off evaluation reports and any exception to a release target (§2a).
- Appoints the custodian; approves B3 retirement and replacement.
- Rules on `unsure` B0 review decisions.

**Access:**
- B0, B1, B2: everything.
- B3: aggregate reports only, unless they are also the custodian, which is not recommended.

**Must not:** label items they later adjudicate or approve alone, when avoidable; give
developers B3 details.

## Annotators (two per item, independent)

**Responsibilities:**
- Label items independently, following the guideline version they were given, using the
  primary pages.
- Record their evidence (URLs) and confidence for each item.
- Flag unclear items and guideline gaps; never resolve them by talking to the other annotator.
- Take part in the 20-item pilot and the agreement check.

**Who:** for date and match cases, team members trained on the guidelines (§2b allows this),
with a domain expert where the field needs one, e.g. to tell a proceedings summary from the
paper. B1 should use annotators who did not build the system's rules.

**Access:**
- Their own assignment and the guidelines.
- **Not** the other annotator's labels until both have submitted.
- **Not** the system's output for their items (no matcher decisions, resolved dates or B0
  reports for those works).
- B3 annotators work only inside custodian storage.

## Adjudicator

**Responsibilities:**
- Resolves every disagreement between annotators A and B and records the final label, the
  reason and the evidence.
- Escalates disagreements caused by the guideline, rather than by error, to the evaluation
  lead with a proposed guideline change.
- Reviews a sample of items where both annotators agreed (suggested 10%) to catch shared
  errors.

**Who:** a senior person per field (§2b). Not one of the two annotators of the item.

**Access:**
- Both annotators' labels for the items they adjudicate.
- No system output.
- For B3: inside custodian storage only.

## B3 custodian

**Responsibilities:**
- Runs the B3 checklist (`B3_CHECKLIST.md`): storage, access control, hashing, overlap
  checks, locked runs, aggregate-only reports, audit log, retirement and replacement.
- Receives B3 labels from annotators and the adjudicator inside custodian storage; never
  forwards items, labels or per-item results to developers.
- Publishes only the B3 work-hash list (for overlap checks) and aggregate reports.

**Who:** one person not involved in prompt or rule development (§2b), with a named deputy
for absences.

**Access:**
- Full access to B3 and its recordings.
- Developers, the AI coding assistant, CI and the shared cloud environments have **none**.

**Must not:** develop or tune the system; share B3 with an AI system; run B3 on a machine or
in a container used for development.

## Developers (including AI coding assistants)

Developers build the harness, use B0 freely, use B1 only for calibration and never access
B3. An AI assistant may pre-annotate B0 only, and must not:
- annotate B1–B3;
- adjudicate;
- approve labels;
- hold any role in the table above.

## Before M1a can close

- [ ] Evaluation lead named and accepted (D19: before M1a ends)
- [ ] B3 custodian named and accepted (D19: before M1a ends)
- [ ] Conflicts declared for both
- [ ] Annotators and adjudicator named (D19 allows this before M1b calibration; needed
      earlier if B1 for G-MATCH / G-LATEST-DATES is to start in M1a)
