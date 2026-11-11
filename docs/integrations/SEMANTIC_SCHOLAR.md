# Semantic Scholar integration

Client: `backend/src/researchpilot/integrations/semantic_scholar.py`; enrichment:
`services/papers/enrich.py`. Fixtures: `backend/tests/fixtures/sources/semantic_scholar/`.

Verified on 2026-11-11 (no API key available; the key request was declined):

| Behaviour | Evidence | Consequence |
|---|---|---|
| Without a key, every request from this environment was refused: HTTP 429, `{"message": "Too Many Requests. Please wait and try again or apply for a key…", "code": "429"}`, `x-amzn-errortype: TooManyRequestsException`, **no `Retry-After`** | recorded `paper_arxiv_1512.03385_unauthenticated.json` (repeated attempts minutes apart) | Without `S2_API_KEY` one attempt is made and the source is reported `unavailable` in the add-paper coverage; adding a paper never depends on it |
| With a key: sent as `x-api-key`; 1 request per second by default | published API documentation | Policy: 1 request/s, 3 attempts with jittered backoff |

**Not verified live:** successful responses. The parser follows the published Graph API
schema (`paperId`, `corpusId`, `externalIds` with `DOI`, `ArXiv`, `PubMed`, `PubMedCentral`,
`CorpusId`, `publicationDate` = `YYYY-MM-DD` or null, `authors[].name`). The one success
fixture, `paper_arxiv_1512.03385_CONSTRUCTED.json`, is **constructed, not recorded**; it is
marked `"constructed": true` in `_recorded.json`, never served by default, and used only by
the tests that say so. It should be replaced by a recording once a key is available.

Use: Semantic Scholar merges versions, so a record listing both a DOI and an arXiv ID is
**strong** Version Matcher evidence (with title ≥ 0.92 and author overlap ≥ 0.6 including
the first author it auto-matches, e.g. ResNet arXiv ↔ CVPR). `publicationDate` is a
secondary claim with unknown upstream.
