# G-MATCH - split B0 (dataset b0-v0.1)

Generated 2026-11-12 22:00 UTC by `scripts/run_benchmarks.py`. **Split: B0.**

- git_sha: `f13ce4d44866`
- version_matcher_rules: `d29-v1`
- dataset_sha256: `3d5a86ad4a4994ed`
- recordings: `benchmarks/recordings, tests/fixtures/sources`

## Verdict

NOT a release decision: B0 development split; all gates pass on these cases. Release targets can only be judged on expert-labelled B3 run by the custodian.

## Dataset

Development split (B0) of G-MATCH: real record pairs from arXiv, Crossref, bioRxiv/medRxiv (and Semantic Scholar where recorded), chosen to cover each category of EVALUATION_FRAMEWORK §2. Labels are AI-proposed from the evidence quoted per case and await team review; they are not gold and support no release claim.

- Cases: 52; categories: ambiguous_no_link 7, comment_reply 6, correction_notice 8, explicit_link_different_title 1, part_series 2, preprint_journal 14, preprint_versions 4, related_extends 2, similar_title_different 8
- Provenance: recorded 52
- Labels: ai_proposed 52 - **AI-proposed labels are not gold** (EVALUATION_FRAMEWORK §2a): they await review against primary pages by a team member.

## Methodology

Each case runs the production code paths on a scratch database from recorded source responses (no network): ingestion from the system of record, version links, the Version Matcher, the Date Resolver, announcement capture and the release-type classifier. Unrecorded aggregator lookups (OpenAlex, Semantic Scholar) are answered 'unavailable'; unrecorded system-of-record requests make a case not evaluable (never scored).

Targets: auto-merge precision >= 0.995; recall >= 0.98 (decisive links) and >= 0.70 (without; the rest as possible matches); 0 merges of adversarial similar-title pairs; merges reversible (EVALUATION_FRAMEWORK §3.1).

## Gates

- [x] every case evaluable
- [x] no false-positive merge
- [x] no adversarial merge
- [x] no ambiguous pair merged
- [x] no order dependence
- [x] merges reversible
- [x] rejections sticky

## Metrics

| Metric | Value |
|---|---|
| cases | 52 |
| scored | 52 |
| not_evaluable | none |
| accuracy | 1.0 |
| auto_merge_precision | 1.0 |
| false_positive_merges | none |
| adversarial_merges | none |
| recall_decisive | 1.0 |
| recall_without_decisive_link_merged_or_possible | 1.0 |
| false_negatives | none |
| ambiguous_kept_possible | 1.0 |
| ambiguous_merged | none |
| related_not_same_detected | 1.0 |
| order_dependent | none |
| reversible | 1.0 |
| rejection_sticky | 1.0 |

### Expected -> observed

| Pair | Count |
|---|---|
| auto_match -> auto_match | 19 |
| no_match -> no_match | 15 |
| possible_match -> possible_match | 7 |
| related_not_same -> related_not_same | 11 |

### By category

| Category | Cases | Correct |
|---|---|---|
| ambiguous_no_link | 7 | 7 |
| comment_reply | 6 | 6 |
| correction_notice | 8 | 8 |
| explicit_link_different_title | 1 | 1 |
| part_series | 2 | 2 |
| preprint_journal | 14 | 14 |
| preprint_versions | 4 | 4 |
| related_extends | 2 | 2 |
| similar_title_different | 8 | 8 |

## Failures

None.
