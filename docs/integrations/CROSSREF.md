# Crossref integration

Client: `backend/src/researchpilot/integrations/crossref.py`; ingestion:
`services/papers/ingest_crossref.py`. Recorded responses: `backend/tests/fixtures/sources/crossref/`
(`_recorded.json` lists each request URL, status and rate-limit headers).

Verified on 2026-11-11 against live responses:

| Behaviour | Evidence | Consequence |
|---|---|---|
| Public pool limits are sent on every response: `x-rate-limit-limit: 5`, `x-rate-limit-interval: 1s`, `x-concurrency-limit: 1`, `x-api-pool: public-single` | all recorded responses | One request per 0.25 s per source, shared across processes. A contact address (`CONTACT_EMAIL`) is added to the User-Agent only when configured (polite pool) |
| Unknown DOI → HTTP 404, plain-text body `Resource not found.` | `10.1234/rp-does-not-exist` | `source_not_found` (404); not counted as a source failure |
| Dates are `date-parts` with 3, 2 or 1 parts | IJTP reprint `issued` = `[1999, 4]` | Stored at 00:00 UTC of the first day with precision day / month / year. Month/year values never count as a release date |
| `issued` is derived (earliest of the publication dates) | eLife: `issued` = `published-online` = 2024-06-03 | Event `issued` (marked derived in the evidence); on equal dates the specific event (`published_online`) is chosen |
| `created`, `deposited`, `indexed` carry timestamps | all records | `index_created`, `metadata_deposited`, `metadata_indexed`: never public-availability events |
| bioRxiv/medRxiv DOIs (`10.1101/…`) are `posted-content`, subtype `preprint`, `institution: [{name: bioRxiv}]` | `10.1101/2022.10.22.513336` | Preprint manifestation, "not peer-reviewed". Crossref dates are **secondary** there (the server API is the system of record), with upstream `biorxiv`/`medrxiv` taken from `institution` |
| On those preprints, `accepted` is the **latest version's posting date** (v3: 2023-11-26), not a journal acceptance | same record vs. bioRxiv `/details` | Not recorded as `accepted` (kept in the source record) |
| Version links are in `relation`, on both sides: `is-preprint-of` (preprint) / `has-preprint` (journal), each with `asserted-by: subject` or `object`; also `is-same-as`, `has-version`, `is-reply-to` | bioRxiv ↔ eLife; insects 17070713 `is-reply-to` 17070712 | Decisive or "related, not same" evidence for the Version Matcher (D29); kept in the source record |
| eLife issues versioned DOIs (`10.7554/eLife.87434.3`) for the same article | eLife record `is-same-as` | The base DOI is the manifestation's identifier; versioned DOIs remain in the record |
| arXiv's author-supplied DOI can point to a reprint rather than the original journal | hep-th/9711200 → `10.1023/A:1026654312961` (IJTP 1999); the ATMP 1998 original is `10.4310/atmp.1998.v2.n2.a1`, an AIP proceedings version is `10.1063/1.59653` | Only the explicitly linked version is decisive; the others are at most possible matches |
| Titles/abstracts may contain JATS/HTML (`<i>de novo</i>`, `<jats:p>`) | bioRxiv record | Markup stripped; raw text kept in the source record |
| Search: deep paging with `cursor=*`, then `next-cursor`; `rows` ≤ 1000 | `relation.type:has-preprint` search, 2 pages of 2 | `CrossrefClient.search()` follows cursors until `max_results` |
| Same title, different items | `10.1038/s43586-024-00294-7` (Corso et al.) and `10.1038/s43586-024-00304-8` (no authors), both "Graph neural networks" | Adversarial pair for the Version Matcher |

**Caching:** entity lookups 7 days, searches 1 hour (separate cache entries per endpoint class).
