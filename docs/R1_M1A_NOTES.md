# R1 M1a (Discover) implementation notes

Scope approved for this round: identifiers, SourceClient, arXiv / Semantic Scholar /
OpenAlex / Crossref / bioRxiv / medRxiv clients, paper manifestations, identifiers and source
records, deduplication and the Version Matcher, date events and the Date Resolver, and arXiv
announcement capture. **Not** in this round: the research objective model and Planner (task 5),
the discovery workflow W1 (task 6), graph-compatible relationship tables (task 6a), and
M1b–M1d. PostgreSQL is the only store; no Neo4j.

## Dependencies

```
identifiers ─┬─> SourceClient ─> clients (arXiv, S2, OpenAlex, Crossref, bioRxiv/medRxiv)
             │                        │
             └─> paper tables (works, manifestations, identifiers, versions, source records)
                         │            │
                         │            ├─> date events ─> Date Resolver ─> release types
                         │            │                       ^
                         │            └─> arXiv announcement capture (RSS) ─┘
                         └─> dedup (identifier union) ─> Version Matcher (needs ≥ 2 sources)
```

* The Version Matcher needs at least two sources that describe the same work differently
  (arXiv plus Crossref or Semantic Scholar), so it follows the second client.
* The Date Resolver's confidence rules are pure and were built first; release types and
  window logic need announcement events and published-version manifestations.
* Announcement capture needs works with arXiv manifestations to attach events to.
* HAS_VERSION scope enforcement (`enforce_relation_scope()` on `paper_manifestations`) needs
  `relation_registry` (task 6a). The manifestation table already has no scope column and is
  registered as a global node source, so adding the check later changes no data.

## First vertical slice: add an arXiv paper by identifier

`POST /api/v1/projects/{id}/papers {"identifier": "..."}` →
identifier parsing → `ArxivClient` (through `SourceClient`: shared rate limit, retries,
circuit breaker, HTTP cache, raw entry stored in `source_records`) → work + arXiv
manifestation + identifier + versions + author list + date events (each with reporting
source, upstream provenance, field path and source record) → Date Resolver → resolved date
on the work → `GET /projects/{id}/papers/{paper_id}` returns every event with its provenance.

Status: implemented and tested (see below). Steps 1–5 of the approved order are done; remaining M1a tasks are listed under Known limitations.

## What exists

| Part | Where | Tests |
|---|---|---|
| Identifier parsing (DOI, arXiv old/new + versions, S2 paper/corpus, OpenAlex, PMID, PMCID; URLs) | `domain/identifiers.py` | `tests/unit/test_identifiers.py` (incl. Hypothesis property tests) |
| `SourceClient` (rate limit, Retry-After, backoff, circuit breaker, HTTP cache, source records) | `integrations/base.py` | `tests/unit/test_source_client.py`, rate limiter in `test_papers_arxiv_slice.py` |
| arXiv API client | `integrations/arxiv.py`, [integration doc](integrations/ARXIV.md) | `tests/unit/test_arxiv_parse.py` (recorded responses), `tests/live/test_arxiv_live.py` (opt-in) |
| Tables: `source_records`, `http_cache`, `source_rate_limits`, `papers`, `paper_manifestations`, `paper_identifiers`, `paper_dates`, `paper_versions`, `paper_source_links`, `paper_authors`, `project_items` | migration `0003`, `db/models/{sources,papers}.py` | `test_migrations.py`, `test_graph_readiness.py` |
| First-public invariant trigger (DATABASE_SCHEMA §14) | migration `0003` | `test_papers_arxiv_slice.py` |
| Date Resolver (confidence rules, flags) | `services/dates/resolver.py`, `store.py` | `tests/unit/test_date_resolver.py` |
| Ingestion and API | `services/papers/`, `api/routers/papers.py` | `tests/integration/test_papers_arxiv_slice.py` |

## Step 1: Crossref

| Part | Where | Tests |
|---|---|---|
| Crossref client: DOI lookup, cursor-paginated search, JATS stripping, partial dates, relations | `integrations/crossref.py`, [integration doc](integrations/CROSSREF.md) | `tests/unit/test_crossref.py` |
| Ingestion: published / preprint / other manifestations, one event per Crossref date field with field-path evidence; bioRxiv/medRxiv records secondary with upstream from `institution` | `services/papers/ingest_crossref.py` | `tests/integration/test_papers_crossref.py` |
| Add by DOI (non-arXiv DOIs go to Crossref) | `services/papers/service.py` | same |
| Resolver tie-break: on equal dates, the specific event beats Crossref's derived `issued` | `services/dates/resolver.py` | `test_date_resolver.py` |

## Step 2: bioRxiv and medRxiv

| Part | Where | Tests |
|---|---|---|
| Client per server: `/details` by DOI (all versions), interval pages with offset cursors, `/pubs` links; "no posts found" = not found; shared request budget for the host | `integrations/biorxiv.py`, [integration doc](integrations/BIORXIV.md) | `tests/unit/test_biorxiv.py` |
| Ingestion: preprint manifestation, primary v1 `preprint_posted`, v2+ `version_posted`, versions table; same DOI from Crossref joins the same manifestation as secondary events | `services/papers/ingest_biorxiv.py` | `tests/integration/test_papers_biorxiv.py` |
| Routing: `10.1101/YYYY.MM.DD.N…` DOIs → likely server, then the other, then Crossref (also when the API is down: date stays unconfirmed) | `services/papers/service.py` | same, `test_papers_crossref.py` |
| `SourcePolicy.rate_limit_key`: several sources on one host share a request budget | `integrations/base.py` | `test_biorxiv.py` |

## Step 3: Version Matcher (D29)

| Part | Where | Tests |
|---|---|---|
| Pure matcher: decisive / strong / supporting / contradicting evidence, versioned rules (`d29-v1`) | `services/matching/version_matcher.py` | `tests/unit/test_version_matcher.py` (incl. Hypothesis: title similarity alone never matches; outcome symmetric) |
| Stated links per manifestation (arXiv author DOI, Crossref `relation`, bioRxiv/medRxiv `published`), derived index `paper_version_links` | `services/matching/links.py`, ingestion modules | integration tests below |
| Candidates (links in both directions + trigram-similar titles), decisions (`paper_match_decisions`), reversible merges (`paper_merge_events`), split, confirm/reject, sticky user decisions (trigger) | `services/matching/store.py`, migration `0005` | `tests/integration/test_version_matching.py` |
| Add-paper flow: ingest → follow decisive links (≤ 3, one level) → match → project membership on the surviving work | `services/papers/service.py` | all paper integration tests |
| API: `GET /projects/{id}/papers/{paper_id}/matches`, `POST /projects/{id}/matches/{decision}/confirm` / `reject`, `POST /projects/{id}/merges/{merge}/split` | `api/routers/papers.py` | `test_version_matching.py`, route inventory |

Real recorded cases (all in `test_version_matching.py`, `test_papers_biorxiv.py`, `test_papers_crossref.py`):

| Case | Result |
|---|---|
| bioRxiv `10.1101/2022.10.22.513336` ↔ eLife `10.7554/elife.87434` (and its versioned DOI `.3`), in either order | One work, three manifestations; first public appearance = verified bioRxiv posting 2022-10-22, not the 2024-06-03 journal date |
| medRxiv `10.1101/2023.12.14.23299828` ↔ JAMA Pediatrics `10.1001/jamapediatrics.2024.1379` (titles completely different) | Auto-matched by the stated link only (title similarity < 0.9) |
| arXiv `hep-th/9711200` → author DOI → IJTP reprint `10.1023/A:1026654312961` | Auto-matched; date `uncertain` (journal known only to the month, so `submission_only` does not apply) |
| Same paper's ATMP original and AIP proceedings version (same title and author, no identifier link) | Possible matches: listed with evidence, not merged; confirm merges, split restores exactly and is remembered as rejected |
| *Neural networks and logistic regression* Part I ↔ Part II (same authors, title similarity > 0.95) | No match (`part_number_differs`) |
| Two *Nature Reviews Methods Primers* records titled "Graph neural networks", one without authors | No match (author overlap cannot be established) |
| Comment `10.3390/insects17070712` ↔ reply `10.3390/insects17070713` | Related, not same; cannot be merged (422) |
| ResNet arXiv `1512.03385` ↔ CVPR `10.1109/cvpr.2016.90` (no identifier link yet) | Possible match until Semantic Scholar/OpenAlex evidence (step 4) |

## Step 4: Semantic Scholar and OpenAlex

| Part | Where | Tests |
|---|---|---|
| OpenAlex client: free work lookups, budgeted search, usage headers, budget-429 stop without retries, own daily cap, `basic`/`premium` capability switch (D24) | `integrations/openalex.py`, [integration doc](integrations/OPENALEX.md) | `tests/unit/test_aggregators.py` |
| Semantic Scholar client: Graph API lookup, optional `x-api-key`; without a key one attempt (429 has no `Retry-After`) | `integrations/semantic_scholar.py`, [integration doc](integrations/SEMANTIC_SCHOLAR.md) | same |
| `SourceClient`: per-source headers (API keys) and a provider-neutral `UsageBudget` hook | `integrations/base.py` | same |
| Enrichment after adding a paper: aggregator IDs, secondary `reported_publication_date` (upstream unknown), OpenAlex `index_created`/`metadata_updated`, "same record lists these identifiers" links (strong evidence); outcome per source returned as `coverage` | `services/papers/enrich.py`, `services/papers/service.py` | `test_papers_arxiv_slice.py`, `test_papers_biorxiv.py`, `test_version_matching.py` |
| Add by OpenAlex / Semantic Scholar ID (resolved to the DOI or arXiv ID of a system of record) | `services/papers/service.py` | `test_version_matching.py`, `test_papers_arxiv_slice.py` |

## Step 5: arXiv announcement capture and date resolution

| Part | Where | Tests |
|---|---|---|
| Feed client: announcement day from `pubDate` (US Eastern date), types and versions from `announce_type` / `guid`, empty feeds | `integrations/arxiv_feed.py`, [integration doc](integrations/ARXIV.md) | `tests/unit/test_arxiv_feed.py` |
| `arxiv_announcement_log` (as listed); `new` → primary `preprint_announced`, `replace` → `version_announced`; applied at capture and when a paper is ingested later; affected works re-resolved | migration `0006`, `services/dates/announcements.py`, `services/papers/ingest.py` | `tests/integration/test_arxiv_announcements.py` |
| Daily worker job, once per UTC day (`jobs.dedupe_key`, `enqueue_once`), categories from settings plus projects' arXiv works | `worker/main.py`, `jobs/queue.py` | same |

Real cases: `2611.13190` goes from `submission_only` (2026-11-09) to verified `announced`
(2026-11-11) with the submission event unchanged; `2604.22997`'s v2 replacement is a version
event and does not make the paper new; capture is idempotent; a failing feed is reported per
category and logs nothing.

## Semantic Scholar with the approved API key

| Part | Where | Tests |
|---|---|---|
| Key from `S2_API_KEY` (`SecretStr`), sent only as `x-api-key`; redacted from logs; never in errors, fixtures or Git | `core/settings.py`, `integrations/registry.py` | `test_semantic_scholar.py::test_the_key_never_appears_in_logs_or_errors` |
| One global limiter for every Semantic Scholar endpoint (`rate_limit_key = semantic_scholar`), 1.25 s minimum interval, shared by API and worker via Postgres | `integrations/semantic_scholar.py`, `integrations/base.py` | `test_semantic_scholar.py`, `test_s2_global_rate_limit.py` (two processes, three endpoints, real timing) |
| 429 handling: `Retry-After` honoured, otherwise jittered exponential backoff; the deferral applies to **all** processes (`RateLimiter.defer`); retries, cache, circuit breaker and graceful degradation kept | `integrations/base.py` | same |
| New endpoints: `/paper/search`, `/paper/{id}/references` (offset pagination) | `integrations/semantic_scholar.py` | `test_semantic_scholar.py` |
| Authenticated and unauthenticated modes | fixture transport serves authenticated recordings only when the header is sent | unit + `authenticated_client` integration tests |
| Real authenticated recordings replace the constructed fixture | `tests/fixtures/sources/semantic_scholar/` | ResNet arXiv ↔ CVPR merge test |
| Attribution requirements and website placement | [ATTRIBUTION.md](ATTRIBUTION.md) | — |

## Release types and date windows (task 4a)

What already existed and was reused: per-manifestation date events with provenance, the
Date Resolver (confidence, first public appearance, `submission_only`), announcement capture,
the Version Matcher, `users.timezone`. What was missing and is now built:

| Part | Where | Tests |
|---|---|---|
| Explicit publication type per manifestation (preprint, journal article, conference paper, …, correction, retraction, expression of concern); migration `0007` with backfill; notices detected from Crossref `update-to`/`updated-by`, linked to originals as related-not-same | `domain/enums.py`, `services/papers/ingest*.py`, `integrations/crossref.py`, migration `0007` | `test_releases.py` (real correction + retraction) |
| Windows: rolling 7 days `[now − 168 h, now)`, custom ranges as UTC days or offset instants, ≤ 366 days; date-only = UTC day with `boundary_day`; month/year never in windows ≤ 31 days | `domain/windows.py` | `tests/unit/test_windows.py` (R1-48 boundaries; property: zone never changes membership) |
| Local display: IANA zones with DST, abbreviations, date-only values never shifted; `tzdata` dependency so slim images have the zone database | `domain/windows.py` | DST transitions Europe (2026-10-25) and North America (2026-03-08, 2026-11-01), UTC+5:30, UTC+14 |
| Release-type classifier (new preprint, new publication, published version of an earlier preprint, revised version, correction notice, older paper newly indexed, date uncertain) | `services/dates/release_types.py`, `services/dates/releases.py` | `tests/unit/test_release_types.py` (30 cases incl. properties: later journal dates never make an announced preprint new; unconfirmed dates never promoted) |
| API: `GET /projects/{id}/releases` (window, counts, entries with local display), `GET/PUT /me/preferences` (display time zone), `?tz=` on paper detail | `api/routers/releases.py`, `api/routers/papers.py` | `tests/integration/test_releases.py` (14 cases on real records) |

Real cases: arXiv `2611.13190` → new preprint (announced 2026-11-11); `2604.22997` v2 →
revised version; bioRxiv → eLife: new preprint in Oct 2022, revised version in Mar 2023,
published version of an earlier preprint in Jun 2024 (never new research); Crossref correction
and retraction notices → correction notice; CVPR 2016 first seen now → older paper newly
indexed.

## Decisions and deviations

| # | Topic | What was done | Why |
|---|---|---|---|
| 1 | arXiv `updated` | Stored as `version_submitted` of the latest version, not `metadata_updated` | Verified: it is the latest version's submission time (integration doc) |
| 2 | `submission_only` vs. "`preprint_submitted` can never be the first public event" (DATABASE_SCHEMA §14) | The trigger allows `preprint_submitted` as the first public event **only** with basis `submission_only`, from the arXiv API v1, when the work has no public-availability claim at all (correction 1 below) | The two rules contradicted each other; §14 now states this rule |
| 3 | `paper_versions` key | `(manifestation_id, version)` plus `paper_id` | Versions belong to a manifestation; a work can have arXiv and bioRxiv versions |
| 4 | Authors | `paper_authors` per manifestation with raw names; `author_id` empty until author resolution; `authors` table not created yet | Author identity needs S2/OpenAlex author IDs or ORCID; creating author nodes from raw names would create false identities |
| 5 | `papers.embedding` | Not created yet | The embedding model is chosen with M1b signals |
| 6 | Corroboration | Only from public-availability events (not bare "publication date" claims) | The first public event must be a public-availability event (§14 trigger) |
| 7 | Secondary agreement | Claims within ±1 day agree; further apart = `conflicting` | §4.8.3 defines ±1 day for corroboration and 2 days only for primary conflicts |
| 8 | Cross-process rate limit | New table `source_rate_limits` (atomic slot reservation) | API and worker are separate processes; an in-process bucket could exceed arXiv's limit |
| 9 | Retries | Implemented in `SourceClient` (no `tenacity` dependency) | Small, fully tested, deterministic with an injected clock |
| 10 | Adding a paper | Synchronous in the API request (one source call, rate-limited) | Manual add is a single lookup; discovery runs go through the worker (W1) |
| 11 | Capability errors | New `GraphCapabilityUnavailable` keeps the code `graph_capability_unavailable`; other features use `capability_unavailable` | R0 mapped every capability error to the graph code |
| 13 | Crossref `accepted` on preprints | Not recorded as `accepted` for `posted-content` | It is the latest preprint version's date (verified), not a journal acceptance |
| 14 | Crossref `created` | Stored as `index_created` | Registration of the DOI record in Crossref; never a public-availability event |
| 15 | Upstream of Crossref dates | `crossref` for DOIs it registers; `biorxiv`/`medrxiv` for those servers' preprints (from `institution`) | Crossref exposes the depositing server; agreement with the server's own API is therefore not independent corroboration |
| 16 | bioRxiv/medRxiv request rate | 1 request/s shared by both servers | No published limit; one host |
| 17 | Preprint server outage | Falls back to Crossref so the paper can still be added, with an unconfirmed date | Coverage over failure; the date is never overstated |
| 18 | No-identifier auto-match | Disabled: such pairs are at most possible matches | The rule needs abstract similarity from embeddings (≥ 0.90), which arrive with M1b; until then a human confirms |
| 19 | Contradictions | A contradicting feature (Part I/II, comment/reply/erratum markers on one side, thesis vs article, disjoint authors, different first author without an identifier link, implausible date order) blocks auto-match **and** possible match; with decisive evidence it gives a possible match | Adversarial pairs should not even be proposed as "possibly the same work" |
| 20 | Merge representation | `papers.merged_into_id`; the merged work's row and graph node stay; its manifestations and all their rows move to the older (surviving) work; `paper_merge_events.moved` records manifestation ids and project memberships, so a split is exact | Reversibility (R1-46) without deleting identities |
| 21 | `paper_version_links` (new table) | Derived index of links stated in source records, per manifestation | Finds candidate pairs in both directions; rebuildable from `source_records` |
| 22 | Following links | After adding a paper, the targets of its decisive links are fetched (one level, at most 3, failures only reduce coverage) | Makes preprint ↔ journal pairs appear without a separate search |
| 23 | Earlier unconfirmed version (resolver) | If another manifestation has a secondary public claim > 2 days before every primary event, the date is `conflicting` (ARCHITECTURE §4.8.3 updated) | Found with the bioRxiv-outage case: otherwise the 2024 journal date would have been "verified" for a work public since 2022 |
| 24 | Strong links | Crossref `is-same-as` / `is-version-of` / `has-version` and (step 4) "both identifiers on one S2/OpenAlex record" are strong, not decisive | ARCHITECTURE §4.8a lists only preprint relations as decisive |
| 25 | Semantic Scholar without a key | One attempt, reported `unavailable` | Keyless requests always got 429 without `Retry-After` (with the approved key, see the section above) |
| 34 | Global 429 deferral | A 429 from any source pushes back the shared slot for every process, by `Retry-After` or by backoff (capped at 120 s) | Retrying processes must not each keep hitting a limited source |
| 35 | S2 minimum interval | 1.25 s (approved limit 1 request/s across all endpoints) | Margin for clock and network jitter; 429s still occur occasionally and are handled |
| 26 | OpenAlex without a key | Entity lookups (free) used; metered queries stop on the budget 429 and are refused until the reset; never retried | The keyless budget is shared per IP and was already used up |
| 27 | OpenAlex filled-in dates | `YYYY-MM-01` → month precision, `YYYY-01-01` → year precision | Verified: missing parts are filled with 01 |
| 28 | Aggregator IDs and dates | Attached to the looked-up manifestation (published DOI first); an ID already held by another work is not duplicated - the listing link lets the matcher compare the works | Both aggregators merge versions; their data is never primary |
| 29 | Effect on arXiv papers | OpenAlex reports a publication date for almost every arXiv paper; under the approved rule (a public claim of any kind rules out `submission_only`) such papers are `single_source` / unconfirmed until a primary event exists - which announcement capture (step 5) provides | Consequence of the corrected `submission_only` rule, now visible |
| 30 | Cross-listings | `cross` / `replace-cross` never produce announcement events | Verified: they can list old papers |
| 31 | `new` with a version > 1 | `preprint_announced` (version recorded in the evidence) | The first announcement of a paper replaced before it was announced |
| 32 | Capture schedule | Once per UTC day after 06:00 UTC via the job queue (`jobs.dedupe_key`), not a separate scheduler | The feed is rebuilt ~05:00 UTC and keeps no history; no new infrastructure (§4.8.5) |
| 33 | Categories | Configured list plus primary categories of projects' arXiv works | Objective-based category mapping arrives with M1c |
| 36 | Correction notice | New release type `correction_notice` (and publication types correction/retraction/expression of concern) | Requested; notices are never research and must not appear as new publications |
| 37 | Release types computed on read | `GET /projects/{id}/releases` classifies from stored events each time; no new table | Classification depends only on stored events and the window; snapshots and "Reclassified" badges belong to Latest Research scans (M1c, `latest_scan_entries`) |
| 38 | Custom ranges | UTC calendar days or offset timestamps; the user's zone is display-only | EVALUATION §3.8 / R1-47: results must be identical whatever the zone |
| 39 | New publication with a known earlier preprint | *Date uncertain*, not *New publication* | §4.8.4 requires that no earlier manifestation is known; covers the approved Nov 8 / Nov 15 case |
| 40 | Unconfirmed first date | Revision / newly indexed only with primary evidence of existence before the window; otherwise *Date uncertain* | Nothing unconfirmed is promoted; a v2 still proves an older v1 when v1 is primary-dated |
| 41 | `/me/preferences` | Display time zone (IANA, validated); allow-listed in the route inventory as user-level | ARCHITECTURE §4.11 contract |
| 12 | Network access | A personal `researchpilot` cloud environment allows only the six source hosts | Required to verify source behaviour; CI uses recorded responses only |

## Corrections after review of 7f447bc

| # | Issue | Fix | Tests |
|---|---|---|---|
| 1 | The Date Resolver put the `submission_only` fallback in the same pool as real public events and took the earliest, so an unannounced arXiv submission (Nov 8) beat a journal's online publication (Nov 15) | The fallback applies only when the work has **no public-availability claim** of any kind: no primary or secondary announcement, posting, online, issue or issued v1 event and no reported publication date, at any precision, on any manifestation (claims more than a day in the future are ignored). Otherwise primary events decide, then the normal secondary rules (`corroborated`, `source_agreement`, `single_source`, `conflicting`); a public claim known only to the month or year gives `uncertain`. When a primary public event wins over an earlier submission, the reason says that an earlier arXiv submission exists. The submission event is never changed or deleted. Migration `0004` aligns the first-public trigger (`submission_only` refused whenever such a claim exists); its downgrade restores the 0003 rule | `test_date_resolver.py`: journal after unannounced submission; OpenAlex-only date after submission (`single_source`); two secondary sources (`source_agreement`); month-precision issue (`uncertain`); future and metadata dates do not block the fallback. `test_papers_arxiv_slice.py`: the trigger refuses `submission_only` once a journal `published_online` event exists, re-resolving selects the journal event, and the submission row is byte-for-byte unchanged |
| 2 | `cache_key()` ignored the endpoint class, so the same URL and parameters requested as a search (1 h TTL) and an entity lookup (12 h TTL) shared one entry and one expiry | The key is now (source, endpoint class, URL, sorted parameters); behaviour within one endpoint class is unchanged. Existing entries under the old key format simply stop matching and expire | `test_source_client.py`: same URL under `search` and `entity` gives two entries; after 2 h the entity entry still hits and the search entry is refetched; key is independent of parameter order |

Both regression suites fail on 7f447bc and pass after the fix.

## Doc issues found (resolved)

* ARCHITECTURE §4.8.2 listed arXiv `updated` as a metadata date (deviation 1): corrected;
  `version_submitted` now names arXiv `updated` as its source.
* DATABASE_SCHEMA §14 contradicted §4.8.4 on `preprint_submitted` (deviation 2): §14 now
  allows it only as the `submission_only` event under the rule above, and lists the
  basis/event pairs the trigger enforces.
* ARCHITECTURE §4.8.4 (and §4.8.5, §10) now state that `submission_only` applies only when no
  other public-availability event is known, with the Nov 8 / Nov 15 example.

## Known limitations (after steps 1–5)

* **Semantic Scholar** works with the approved key; without `S2_API_KEY` it is reported
  `unavailable`. Even with the key, occasional 429s occur at 1.25 s spacing; they are retried
  with a global backoff and can make a call report `unavailable`. The standard API licence
  covers internal non-commercial research/education; a public site may need an expanded
  licence (see ATTRIBUTION.md).
* **OpenAlex** keyless budget is shared per IP and was used up from this environment: list
  queries stop until midnight UTC; single-work lookups still work.
* **Unannounced arXiv papers** with an OpenAlex date are `single_source` (unconfirmed), not
  `submission_only`, under the approved rule; announcement capture fixes this only from the day
  capture runs (feeds keep no history).
* The no-identifier auto-match needs abstract embeddings (M1b); such pairs are possible matches.
* Announcement capture categories come from settings and projects' arXiv works until M1c.
* Release types are computed on read; there are no snapshots, so a reclassification is not
  flagged as such until Latest Research scans (M1c) store entries.
* "No earlier preprint found in" lists the sources whose records the work has; it does not run a
  new search for an earlier preprint (scans in M1c do).
* Corrections are recognised from Crossref `update-to`; notices without it (e.g. some
  publishers, other registries) are classified by their type only.
* The frontend has no `LocalTime` component or Latest Research page yet (M1c); the API already
  returns the local display strings.
* Not started (outside this round): research objective + Planner (task 5), discovery workflow
  W1 with search log (task 6), graph-compatible relationship tables (task 6a), G-MATCH and
  G-LATEST-DATES benchmark sets (D19 evaluation roles).
