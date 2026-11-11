# bioRxiv and medRxiv integration (D22)

Client: `backend/src/researchpilot/integrations/biorxiv.py` (one client per server);
ingestion: `services/papers/ingest_biorxiv.py`. Recorded responses:
`backend/tests/fixtures/sources/biorxiv/`.

Verified on 2026-11-11 against live responses:

| Behaviour | Evidence | Consequence |
|---|---|---|
| `/details/{server}/{doi}` returns **one row per version**: `version`, `date` (that version's posting date, day precision), title, authors (`Chen, X.; Li, Y.`), category, license, `published` (journal DOI or `NA`), `server` | `10.1101/2022.10.22.513336`: v1 2022-10-22, v2 2023-03-04, v3 2023-11-26, `published = 10.7554/elife.87434` | System of record for posting dates: v1 → `preprint_posted` (primary, public availability), v2+ → `version_posted` (never a first appearance). `published` kept for the Version Matcher |
| Author lists can change between versions | v3 adds "Gao, C." | The manifestation's author list follows the latest version; every version stays in the source record |
| Unknown DOI, or a DOI asked on the other server → HTTP 200, `messages[0].status = "no posts found"`, empty collection | `10.1101/2099.01.01.000000`; medRxiv DOI on `/details/biorxiv/…` | Not found; the other server is tried, then Crossref |
| `/details/{server}/{from}/{to}/{cursor}`: **30 rows per page**; the cursor is an item offset; `messages[0].total` gives the total | 2024-06-03: total 301, cursor 0 → rows 0–29, cursor 100 → rows 100–129 | `details_in_interval()` advances the cursor by `count` until `total` |
| `/pubs/{server}/{from}/{to}/{cursor}`: preprint → published links (`preprint_doi`, `published_doi`, `published_journal`, `preprint_date`, `published_date`) | 2024-06-03: 49 bioRxiv and 15 medRxiv links | Decisive Version Matcher evidence |
| Posting date ≠ date in the DOI | DOI `2023.10.03…` posted 2023-10-05 | Dates are never derived from DOIs |
| medRxiv DOIs have 8-digit suffixes, bioRxiv 6 | `…23299828` vs `…513336` | Only a lookup-order hint; both servers are tried |
| `10.1101/` is also Cold Spring Harbor's journal prefix (`10.1101/gad.…`) | — | Only DOIs shaped `10.1101/YYYY.MM.DD.NNNNNN[NN]` are routed to the servers; others go to Crossref |
| No published rate limit; one host for both servers | — | One request per second, one shared budget for bioRxiv and medRxiv (`SourcePolicy.rate_limit_key`) |
| The same preprints are also in Crossref (`posted-content`) | see CROSSREF.md | Same DOI → same manifestation; Crossref's dates are added as secondary events (upstream `biorxiv`/`medrxiv`, so not independent) |

Every bioRxiv/medRxiv manifestation is labelled "Preprint — not peer-reviewed".
