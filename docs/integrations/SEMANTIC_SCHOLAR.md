# Semantic Scholar integration

Client: `backend/src/researchpilot/integrations/semantic_scholar.py`; enrichment:
`services/papers/enrich.py`. Recorded responses (authenticated, 2026-11-11):
`backend/tests/fixtures/sources/semantic_scholar/`.

## Configuration

| Setting | Meaning |
|---|---|
| `S2_API_KEY` | Approved API key, read from the environment (a `SecretStr` setting). Sent only as the `x-api-key` request header. Never hard-coded, logged, returned by the API or stored in fixtures. Unset = unauthenticated mode |

In a Claude Code cloud session the key is a **network secret** (header `x-api-key`) that the
session proxy adds to requests for `api.semanticscholar.org`; no environment variable holds
it. To run the app there with the key, set `S2_API_KEY=proxy-injected` (a placeholder the proxy
overwrites). In Docker Compose or a hosted deployment, set `S2_API_KEY` from the secret store.

## Rate limit (approved: 1 request per second, cumulative across ALL endpoints)

* Every endpoint (`/paper/{id}`, `/paper/search`, `/paper/{id}/references`, and any added
  later) goes through **one** `SourceClient` whose limiter key is `semantic_scholar`.
* The limiter is `PostgresRateLimiter`: an atomic next-slot reservation in
  `source_rate_limits`, shared by the API and worker processes (and any number of replicas).
* Conservative minimum interval: **1.25 s** between requests (`S2_MIN_INTERVAL_SECONDS`).
* On HTTP 429 the shared slot is deferred **for every process** (`RateLimiter.defer`): by
  `Retry-After` when sent, otherwise by jittered exponential backoff (2 s base, 30 s cap);
  4 attempts with a key, then the source is reported unavailable for that call. Three failed
  calls in a row open the circuit breaker (degraded for 10 minutes, calls fail fast).
* Without a key: one attempt per call (a keyless 429 does not clear by retrying).
* A failure never blocks adding a paper: the add-paper response reports
  `coverage.semantic_scholar` as `ok`, `not_found`, `unavailable` or `budget_exhausted`.

## Verified behaviour (2026-11-11)

| Behaviour | Evidence | Consequence |
|---|---|---|
| With the key, single requests return 200 | ResNet, eLife, CVPR records | Recorded as fixtures |
| Concurrent requests with the key: **429**, `x-amzn-errortype: TooManyRequestsException`, body `{"message": "Too Many Requests…", "code": "429"}`, **no `Retry-After`** | 3 parallel requests: all 429 (`burst_429_with_key.json`) | Client-side backoff and a global deferral are required |
| Occasional 429s even 1.5–3 s apart; recovery after a few seconds | `1706.03762` attempts during recording | 1.25 s is a floor, not a guarantee: 429 handling is part of normal operation |
| Without a key: every request 429 (same body) | `paper_arxiv_1512.03385_unauthenticated.json` | Unauthenticated mode: one attempt, reported `unavailable` |
| Unknown paper: 404 `{"error": "Paper with id DOI:… not found"}` | `paper_DOI_unknown.json` | `source_not_found` |
| `/paper/search`: `total`, `offset`, `next`, `data[]` | 55 050 results, pages of 2 (`next` 2 → 4) | Offset pagination |
| `/paper/{id}/references`: `offset`, `next`, `data[].citedPaper` | ResNet, 3 per page | Offset pagination; ready for citation work |
| `externalIds` merges versions: the ResNet record lists arXiv `1512.03385` and DOI `10.1109/cvpr.2016.90` | `paper_ARXIV_1512.03385.json`, `paper_DOI_10.1109_cvpr.2016.90.json` | **Strong** Version Matcher evidence (auto-matches ResNet arXiv ↔ CVPR with title and authors) |
| The eLife record lists no bioRxiv DOI; its `publicationDate` (2023-11-26) is the bioRxiv **v3** posting date | `paper_DOI_10.7554_elife.87434.json` | `reported_publication_date` is secondary, upstream unknown |

## Licence and attribution

From the API License Agreement (<https://api.semanticscholar.org/license>, read 2026-11-11):

* "any public use of Data must point back to Semantic Scholar at https://www.semanticscholar.org/
  with a utm_source=api UTM parameter and Licensee will also include the Semantic Scholar name
  and logo on any public displays of the Data";
* data made publicly available must include "recognition of the contributions of the
  non-publishing party according to standard practice for assigning scientific credit";
* the standard grant is limited to the licensee's **internal use** for "legitimate,
  non-commercial, research and/or educational purposes"; other uses (including commercial)
  need an expanded licence from Semantic Scholar;
* the API key must not be shared with anyone who is not an authorised user.

Where ResearchPilot shows attribution: see [ATTRIBUTION.md](../ATTRIBUTION.md).
