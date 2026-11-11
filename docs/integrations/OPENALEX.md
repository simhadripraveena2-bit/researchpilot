# OpenAlex integration (D24: basic access, budgeted)

Client: `backend/src/researchpilot/integrations/openalex.py`; enrichment:
`services/papers/enrich.py`. Recorded responses: `backend/tests/fixtures/sources/openalex/`.

Verified on 2026-11-11 against live responses (no API key):

| Behaviour | Evidence | Consequence |
|---|---|---|
| Usage headers on every response: `x-ratelimit-cost-usd`, `x-ratelimit-limit-usd` (0.1), `x-ratelimit-remaining-usd`, `x-ratelimit-reset` | all recordings | `OpenAlexBudget` tracks spend and OpenAlex's remaining budget; our own cap: `OPENALEX_DAILY_BUDGET_USD` (default 0.10) |
| Without a key the daily budget is **shared by every client on the network's IP address**; it was already used up from this environment | 429 body: "counts against the free daily budget shared by everyone on your network's IP address" | Keyless operation is best-effort; a key (`OPENALEX_API_KEY`, sent as `Authorization: Bearer`) gives a separate budget |
| Single-work lookups (`/works/{W}`, `/works/doi:{doi}`) cost $0 and work with no budget left | `x-ratelimit-cost-usd: 0`, `remaining-usd: 0` | Entity lookups are always allowed |
| List/filter queries with the budget used up → HTTP 429, `x-ratelimit-credits-required: 1`, `x-ratelimit-cost-required-usd: 0.0001`, `Retry-After` = seconds to midnight UTC, JSON `error` | `works?filter=doi:…` | `source_budget_exhausted`: never retried; further metered requests refused locally until the reset |
| Unknown work → HTTP 404 with an HTML body | `W999999999999` | `source_not_found` |
| `publication_date` fills missing parts with `01` | CVPR 2016 → `2016-06-01` (Crossref: `2016-06`); ATMP 1998 → `1998-01-01` | `MM-01` stored with month precision, `01-01` with year precision |
| OpenAlex merges versions into one work | bioRxiv `10.1101/2022.10.22.513336` and eLife `10.7554/elife.87434` = `W4372330081`; medRxiv preprint and JAMA Pediatrics = `W4399286025`; arXiv `hep-th/9711200` and the IJTP reprint = `W2166248051` | "Both identifiers on one work" is strong, not decisive, evidence (D29). OpenAlex's work ID is attached to the looked-up manifestation |
| Its dates can belong to neither version, or be plainly wrong | `W4372330081`: 2023-05-05 (preprint 2022-10-22, journal 2024-06-03); arXiv `2411.00001` (submitted 2024-10-08): 2026-06-12 | `reported_publication_date`, **secondary, upstream unknown** (no provenance is exposed); flagged when it disagrees with primary events |
| But arXiv preprints and conference versions can be separate works | `doi:10.48550/arxiv.1512.03385` = `W2949650786` (preprint), CVPR = `W2194775991` | No version evidence from OpenAlex in that case |
| `created_date` / `updated_date` are returned by basic lookups | all works | `index_created` / `metadata_updated` (never public-availability events) |
| `indexed_in` lists the indexes holding the work (`crossref`, `arxiv`, `pubmed`…) | — | Kept as evidence; **not** treated as date provenance |

**Capabilities (D24):** `OPENALEX_CAPABILITIES=basic|premium`. Finding newly indexed works
(`from_created_date` filter) needs `premium`; on `basic` it is refused, never silently
replaced by a publication-date filter. Both paths are tested.

**Rate:** 10 requests per second documented; one request per 0.1 s, shared across processes.
