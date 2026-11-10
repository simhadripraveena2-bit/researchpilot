# 8. External API dependencies and limitations

> Limits below are planning assumptions. Each integration's README in
> `docs/integrations/` must record the limits **as verified on the date the
> integration is implemented**, with links to the official docs. All defaults
> are configurable via environment variables.

## 8.1 Summary

| Source | Role | Auth | Default client limit | Phase |
|---|---|---|---|---|
| arXiv API | preprint search, metadata, abstracts, PDFs | none | 1 request / 3 s, single connection | 2 |
| Semantic Scholar Graph API | search, metadata, citations/references, recommendations, OA PDF links | API key (strongly recommended) | 1 req/s with key; unauthenticated = shared, frequently throttled pool | 2 |
| OpenAlex | broad coverage search, metadata, references, related works, OA locations | **API key required since Feb 2026; usage-based pricing with a free daily allowance** | ~5 req/s; budget per day configurable | 2 |
| Crossref REST | DOI validation, publisher metadata, references (when deposited) | none; polite pool via contact email | ~5 req/s (respect `X-Rate-Limit-*` headers) | 2 |
| Unpaywall | open-access PDF locations by DOI | email parameter | ~5 req/s; 100k/day guideline | 3 |
| GROBID | PDF → TEI XML (sections, references, coordinates) | self-hosted container | bounded by local CPU; concurrency 2–4 | 3 |
| LLM API (Anthropic by default) | planning, extraction, judgement, critique, writing | API key | per-account rate limits; concurrency semaphore | 2 (optional), 3+ |
| Hugging Face Hub | models, datasets, Spaces, paper pages linked to arXiv IDs | optional token | conservative 5 req/s | 5 |
| GitHub REST | repository metadata, search | token | 5,000 req/h core; search ~30 req/min | 5 |
| Papers with Code | — | — | **service discontinued (2025)**; optional frozen dump import | 5 (optional) |
| Google Scholar | — | — | **not integrated** (no API; terms forbid scraping) | — |

## 8.2 arXiv

- **Endpoint:** `http://export.arxiv.org/api/query` (Atom 1.0 XML). Query
  syntax with field prefixes (`ti:`, `abs:`, `au:`, `cat:`), boolean
  operators, `sortBy=submittedDate|relevance|lastUpdatedDate`.
- **Limits/terms:** arXiv asks for no more than one request every three
  seconds and a single connection; large result sets should be paged
  (`start`, `max_results`); very deep paging is unreliable. Bulk access should
  use OAI-PMH or the bulk data on S3, not the query API.
- **Gives us:** title, abstract, authors, categories, versions and dates,
  DOI and journal ref (if authors supplied them), PDF link.
- **Does not give:** citations, references, venues for most papers,
  affiliations (rarely).
- **Quirks:** empty results are returned as a valid feed with zero entries;
  errors can appear as an `<entry>` with an error title — the parser must
  detect this rather than treat it as a paper. Old-style IDs (`hep-th/9901001`).
- **PDFs:** `https://arxiv.org/pdf/<id>v<version>`; respect the same polite
  pacing; record version downloaded. Licences vary per paper (arXiv
  non-exclusive licence vs. CC variants) — stored in `documents.license`.

## 8.3 Semantic Scholar (Academic Graph API)

- **Endpoints used:** `/graph/v1/paper/search` (relevance, ≤ 1,000 results
  reachable via offset), `/graph/v1/paper/search/bulk` (token-paged, larger
  result sets, less relevance-tuned), `/graph/v1/paper/batch` (POST up to 500
  IDs, mixed ID types like `DOI:`, `ARXIV:`), `/graph/v1/paper/{id}/references`
  and `/citations` (paged, with `contexts`, `intents`, `isInfluential`),
  `/recommendations/v1/papers/forpaper/{id}`.
- **Fields:** request explicitly with `fields=` (`externalIds, title,
  abstract, year, publicationDate, venue, publicationVenue, authors,
  citationCount, influentialCitationCount, openAccessPdf, fieldsOfStudy,
  publicationTypes`).
- **Limits:** unauthenticated traffic shares a global pool and gets 429s under
  load; an individual API key gives an introductory 1 req/s across endpoints
  (higher on request). Plan: apply for a key; client defaults to 1 req/s;
  prefer `/paper/batch` to many single lookups.
- **Limitations:** abstracts missing for some papers due to publisher
  restrictions; citation lists for very highly cited papers are large — always
  page with a budget; `openAccessPdf` may point to publisher pages that block
  automated download.
- **Licence:** API terms of use require attribution; data licence terms to be
  reviewed before any redistribution of bulk data.

## 8.4 OpenAlex

- **Endpoints used:** `/works?search=` and `?filter=` (title/abstract search,
  publication year, `ids.doi`, `ids.openalex`, `cites:` for citations),
  singleton `/works/{id}` (also accepts DOI), `per-page` up to 200,
  cursor paging (`cursor=*`).
- **Access model (changed 2026):** an API key is required for all requests;
  usage is metered (free daily allowance, list/search requests cost more than
  singleton lookups, paid tiers above that). Implications:
  - `OPENALEX_API_KEY` is a required setting when OpenAlex is enabled.
  - The client counts usage per run and per day and stops at a configurable
    daily budget, reporting OpenAlex as `budget_exhausted` (not "no results").
  - Prefer filter-by-IDs batch lookups (pipe-separated, up to ~50 IDs per
    request) over many singleton calls.
  - OpenAlex also offers full-text PDF/TEI downloads for some works at a
    per-file cost — evaluated in Phase 3 as an optional, budget-gated source.
- **Gives us:** abstracts (as `abstract_inverted_index`, which we reconstruct;
  some abstracts are withheld), `referenced_works`, `related_works`,
  `cited_by_count`, `open_access` + `best_oa_location`, concepts/topics,
  institutions, authorships with ORCID.
- **Limitations:** title/abstract search is less precise than S2 relevance;
  metadata merges occasionally conflate versions; `related_works` is
  algorithmic and should be labelled as such.
- **Licence:** data is CC0.

## 8.5 Crossref

- **Endpoint:** `https://api.crossref.org/works/{doi}`, `/works?query.bibliographic=`.
- **Polite pool:** include contact email (`mailto` / User-Agent). Respect
  `X-Rate-Limit-Limit` and `X-Rate-Limit-Interval` headers; back off on 429.
- **Use:** authoritative DOI existence check, publisher venue/date, type,
  licence links, references when the publisher deposited them.
- **Limitations:** abstracts are rare (JATS XML when present); author names
  unnormalised; no citation counts beyond `is-referenced-by-count`.

## 8.6 Unpaywall (recommended addition)

- **Endpoint:** `https://api.unpaywall.org/v2/{doi}?email=…`.
- **Use:** `best_oa_location.url_for_pdf`, `license`, `version`
  (submitted/accepted/published), `host_type`.
- **Limitations:** DOI-only; some listed PDF URLs are landing pages or block
  bots. These become `failure_reason=not_a_pdf` / `http_error`, never treated
  as success.

## 8.7 GROBID

- **Deployment:** official Docker image (CPU image is fine for modest volume;
  the deep-learning models run faster/better with GPU). Pin the image version.
- **Endpoint:** `POST /api/processFulltextDocument` with
  `teiCoordinates=s,head,p,figure,table,ref,biblStruct` and
  `consolidateHeader=0` (we already have metadata).
- **Gives us:** sections with headings, paragraphs, figure/table captions,
  bibliography (matched against our citation edges), and page coordinates for
  highlighting.
- **Limitations:** tables are extracted as text, often imperfectly; formulae
  are not reliably captured; scanned PDFs need OCR (out of scope initially —
  reported as `parse_failed: scanned_pdf`).
- **Fallback:** `pypdfium2` page text (page numbers reliable, structure lost).
  PyMuPDF optional, subject to decision D2.

## 8.8 LLM API

- Provider-agnostic `LLMGateway`; default Anthropic implementation with
  structured outputs validated by Pydantic. Default model `claude-opus-5-5`,
  per-agent override via env.
- Handle `refusal` and `max_tokens` stop reasons explicitly; retry 429/5xx with
  backoff (SDK retries + our budget accounting).
- Bulk extraction can use the Message Batches API (asynchronous, lower cost).
- Data sent: paper text and metadata (public or OA content) and the user's
  topic. Documented in the privacy section of the README.

## 8.9 Hugging Face Hub (Phase 5)

- **Endpoints:** `/api/models?search=`, `/api/datasets?search=`,
  `/api/spaces`, model/dataset card metadata, and the paper pages API
  (`/api/papers/{arxiv_id}`) which links papers to models/datasets/Spaces that
  cite their arXiv ID.
- **Limitations:** links depend on authors tagging arXiv IDs in model cards;
  search is name-based; rate limits are not published precisely → conservative
  default and backoff.

## 8.10 GitHub (Phase 5)

- **Endpoints:** `GET /repos/{owner}/{repo}` (stars, licence, pushed_at,
  archived), `GET /search/repositories?q=` (title/arXiv ID search),
  README fetch to confirm the paper is referenced.
- **Limits:** 5,000 requests/hour with a token; search endpoints ~30
  requests/minute; code search requires auth and has stricter limits.
- **Link confidence:** `paper_text` (URL appears in the paper) >
  `hf_paper_page` > `readme_mentions_arxiv_id` > `name_search`. Name-search
  matches are shown as "possible implementation", never "official".

## 8.11 Papers with Code (discontinued)

The site was shut down in 2025 and redirects to Hugging Face. Benchmark
leaderboards are therefore not available as a live API. Options:
1. Skip (default). Benchmarks come from our own `reported_results` extraction.
2. Import an archived dump as a dated, read-only reference table, labelled
   "Papers with Code archive (snapshot date)". Licence CC-BY-SA — attribution
   and share-alike obligations to be confirmed.

## 8.12 Google Scholar

No official API; automated access is prohibited by its terms. Not
integrated. Users can add papers manually by DOI/arXiv ID.

## 8.13 Common failure handling

| Situation | Behaviour |
|---|---|
| 429 / `Retry-After` | wait as instructed (capped), retry; log `source.rate_limited` |
| 5xx / timeout | exponential backoff with jitter, max attempts, then mark query `failed` |
| Repeated failures | circuit opens; source `degraded` for the run; report coverage notice |
| Budget exhausted (OpenAlex usage, LLM tokens) | stop calling, mark `budget_exhausted`, continue with other sources |
| Malformed payload | store raw payload, log validation error, skip record |
| Missing abstract | `abstract_status=unavailable`; try other sources; rank on title |
| Full text unavailable | `documents.retrieval_status=unavailable` with specific reason; analysis falls back to abstract and says so |
