# G-LATEST-DATES - split B0 (dataset b0-v0.1)

Generated 2026-11-12 22:00 UTC by `scripts/run_benchmarks.py`. **Split: B0.**

- git_sha: `f13ce4d44866`
- version_matcher_rules: `d29-v1`
- dataset_sha256: `280009188325ae3f`
- recordings: `benchmarks/recordings, tests/fixtures/sources`

## Verdict

NOT a release decision: B0 development split; all gates pass on these cases. Release targets can only be judged on expert-labelled B3 run by the custodian.

## Dataset

Development split (B0) of G-LATEST-DATES: real recorded records from arXiv (API and the 2026-11-11 announcement feeds), bioRxiv/medRxiv, Crossref and, where recorded, OpenAlex and Semantic Scholar. Labels are AI-proposed from the evidence quoted per case and await team review; they are not gold and support no release claim.

- Cases: 43; categories: arxiv_announced 4, arxiv_cross_listing 7, arxiv_revision 2, arxiv_submission_only 2, conflicting 2, insufficient_evidence 2, journal_of_older_preprint 7, journal_only 4, metadata_vs_public 3, newly_indexed_older 2, reduced_precision 4, server_posted 4
- Provenance: recorded 43
- Labels: ai_proposed 43 - **AI-proposed labels are not gold** (EVALUATION_FRAMEWORK §2a): they await review against primary pages by a team member.

## Methodology

Each case runs the production code paths on a scratch database from recorded source responses (no network): ingestion from the system of record, version links, the Version Matcher, the Date Resolver, announcement capture and the release-type classifier. Unrecorded aggregator lookups (OpenAlex, Semantic Scholar) are answered 'unavailable'; unrecorded system-of-record requests make a case not evaluable (never scored).

Targets: 0 fabricated or mis-typed dates; uncertain dates never confirmed; journal versions of preprints never new research; revisions never new preprints (EVALUATION_FRAMEWORK §3.3, §3.8).

## Gates

- [x] every case evaluable
- [x] no incorrectly verified date
- [x] no uncertain date shown as confirmed
- [x] no journal date over an earlier preprint
- [x] no revision shown as new work

## Metrics

| Metric | Value |
|---|---|
| cases | 43 |
| scored | 43 |
| not_evaluable | none |
| accuracy | 1.0 |
| first_public_date_accuracy | 1.0 |
| confidence_accuracy | 1.0 |
| incorrectly_verified | none |
| uncertain_class_accuracy | 1.0 |
| uncertain_shown_as_confirmed | none |
| conflicts_detected | 1.0 |
| journal_date_over_preprint | none |
| revision_shown_as_new_work | none |
| release_type_accuracy | 1.0 |

### Expected -> observed

| Pair | Count |
|---|---|
| single_source -> single_source | 1 |
| source_agreement -> source_agreement | 2 |
| uncertain -> uncertain | 6 |
| verified -> verified | 34 |

### By category

| Category | Cases | Correct |
|---|---|---|
| arxiv_announced | 4 | 4 |
| arxiv_cross_listing | 7 | 7 |
| arxiv_revision | 2 | 2 |
| arxiv_submission_only | 2 | 2 |
| conflicting | 2 | 2 |
| insufficient_evidence | 2 | 2 |
| journal_of_older_preprint | 7 | 7 |
| journal_only | 4 | 4 |
| metadata_vs_public | 3 | 3 |
| newly_indexed_older | 2 | 2 |
| reduced_precision | 4 | 4 |
| server_posted | 4 | 4 |

## Failures

None.
