# Missing-category coverage plan (G-MATCH, G-LATEST-DATES)

The gaps come from the M1a benchmark report (`reports/README.md`) and the B0 review sheets.
For each gap: what is missing, how to find real cases without using the system's output,
proposed counts, and what blocks it. Counts are proposals for the evaluation lead.

- **B0+** = development cases, added like the current B0 (AI may pre-annotate, marked, then
  team review).
- **B1** = expert-labelled (see `B1_PROTOCOL.md`).
- B3 strata mirror B1 but are drawn by the custodian.

## G-MATCH

| Gap | Now in B0 | How to find real cases (independent of the matcher) | B0+ | B1 | Blockers |
|---|---|---|---|---|---|
| Conference paper vs extended journal version (related, not the same work) | 0 | DBLP pairs of conference and journal entries with overlapping authors and titles; journals' "extended version of" notes | 6 | 25 | Guideline: decide whether an extended version is `related_not_same` (proposed) or `same_work` |
| Thesis vs article from it | 0 | Crossref `dissertation` type with an author who has an article of similar title; university repositories | 4 | 15 | Thesis DOIs are sparse; may need DataCite (not a client today) |
| Same authors, different paper | 1 | Author pages / Crossref author queries: pairs of the same author group within 2 years | 6 | 25 | — |
| Generic titles ("Introduction", "Editorial", "Reply", "Response") | 0 | Crossref title search for common generic titles in one journal | 6 | 25 | — |
| Retitled journal versions (explicit link, different title) | 1 (+4 retitled pairs filed under preprint_journal) | bioRxiv `/pubs` pairs with title similarity < 0.9 | recategorise 4; add 4 | 25 | B0 review decides the recategorisation |
| Third-party copies / re-deposits of a paper | 3 (10.65215) | Crossref `posted-content` with an identical title and authors from an unrelated registrant | 2 | 10 | **Guideline gap:** is a copy the same work? Lead to decide |
| Proceedings summary vs full paper (same title) | 1 (GM-B0-024, unverified) | AIP/IEEE proceedings with a same-title journal paper | 3 | 15 | Needs content check by an annotator |
| Translations / reprints | 1 (IJTP reprint) | Crossref `is-translation-of`, reprint notes | 2 | 10 | — |
| Strong-link (aggregator) cases | 2 | S2 / OpenAlex records listing a preprint and journal DOI | 6 | 30 | **OpenAlex keyless budget exhausted here; S2 key intermittent.** Recording needs a working key / budget |
| Withdrawn preprint vs published paper | 0 | arXiv withdrawn entries; bioRxiv withdrawn notices | 3 | 10 | — |
| Dataset / software DOI with the paper's title | 0 | Zenodo/Figshare DOIs `is-supplement-to` | 3 | 10 | DataCite records not ingested; may be out of scope |
| Larger samples of existing categories | 52 total | as in B0 | to ~100 total | 300 total | Annotator time |

## G-LATEST-DATES

| Gap | Now in B0 | How to find real cases | B0+ | B1 | Blockers |
|---|---|---|---|---|---|
| **Ground-truth date field** (truth separate from policy output) | not in schema | — | schema change (B1_PROTOCOL §2) | required | Code change before B1 |
| Primary vs primary conflict (`conflicting`) | 0 | arXiv records whose API v1 date disagrees with the captured listing; bioRxiv API vs `/pubs` `preprint_date` > 2 days apart; Crossref posted vs server date | 3 | 15 | Rare; needs a search across `/pubs` |
| Secondary vs primary disagreement (flag only) | 3 (OA vs online / posted) | as in B0 | 3 | 15 | — |
| Secondary vs secondary conflict (no primary) | 0 | OpenAlex and S2 disagreeing for a paper whose system of record is unavailable | 3 | 10 | Needs aggregator recordings |
| **Corroborated** (disjoint recorded upstream) | 0 | Claims with recorded different upstreams agreeing within ±1 day | 2 | 10 | **No source today records upstream provenance for aggregator dates** (reported as unknown), so may be impossible to source; the lead decides whether to drop or redefine |
| Secondary-only: OpenAlex only / S2 only | 1 (OA only) | Unannounced arXiv papers with an OpenAlex date only; S2-only | 4 | 15 | Aggregator access |
| Future dates | 0 | Crossref records with a print date in a future issue | 3 | 10 | — |
| Window boundaries (exact start/end, ±1 s, date-only on boundary days) | 0 | Announcement and online dates placed at window edges (windows chosen per case) | 6 | 20 | Needs a case field for window **boundaries in time**, not only dates |
| Time-zone display (UTC±14, DST) | 0 | Same as boundaries plus user time zones | — | 20 | **Display strings are not in the runner yet** (they are in the API); runner extension needed |
| Newly indexed via OpenAlex `created_date` | 0 | Older works with a recent OpenAlex created date | 3 | 10 | OpenAlex budget |
| bioRxiv/medRxiv revisions (v2+ in window) | 0 | bioRxiv `/details` with a recent v2 | 3 | 15 | — |
| Journal version of an arXiv preprint (arXiv DOI link) | 0 (only bioRxiv / medRxiv / ChemRxiv) | arXiv entries with `<arxiv:doi>` published recently | 4 | 20 | — |
| Correction / retraction notices in a window | 1 | Crossref `update-to` notices | 3 | 15 | — |
| Announcement captured on a different day than the true announcement (late capture) | 0 | Capture of an older feed is impossible (feeds keep no history), so this needs prospective daily capture | 0 | 10 | Needs daily recording over weeks (prospective) |
| Larger samples of existing categories | 43 | as in B0 | to ~100 | 250 | Annotator time |

## Order of work

1. B0 review of the current 95 cases (people). Settle the guideline gaps: copies, extended
   versions, proceedings (evaluation lead).
2. Schema change for ground truth (code). Runner support for window boundaries and display
   strings (code).
3. B0+ additions for categories with no blockers (code + AI pre-annotation + team review).
4. Recording access for aggregator categories (OpenAlex budget or key, S2 key): an
   environment/operations decision.
5. B1 sampling per stratum (evaluation lead), then annotation (people).
