# arXiv integration

Client: `backend/src/researchpilot/integrations/arxiv.py`. Recorded responses:
`backend/tests/fixtures/sources/arxiv/`. Live checks (opt-in, `RP_LIVE_SOURCES=1`):
`backend/tests/live/test_arxiv_live.py`.

## API (`https://export.arxiv.org/api/query`, Atom 1.0)

Verified on 2026-11-11 against live responses:

| Behaviour | Evidence | Consequence |
|---|---|---|
| `<published>` is the **v1 submission** timestamp (UTC) | 1706.03762: `2017-06-12T17:57:34Z` = v1 on the abs page | Stored as `preprint_submitted` (v1). Not a public-availability event |
| `<updated>` is the submission timestamp of the **latest version**, or of the version requested with `id_list=<id>vN` | 1706.03762: `updated` = v7 submission `2023-08-02T00:41:18Z`; `id_list=1706.03762v2` → `2017-06-19T16:49:45Z` = v2 submission | Stored as `version_submitted` for that version. **Not** a metadata date (ARCHITECTURE §4.8.2 listed arXiv `updated` under `metadata_updated`; this is corrected here) |
| The entry `<id>` carries the latest version | `.../abs/1706.03762v7` | Latest version number taken from it |
| Version history is not listed | — | Per-version timestamps need one query per version (`id_list=<id>vN`); not fetched in this slice |
| Submission can precede public appearance by weeks | 2411.00001: `published` = 2024-10-08, numbered (announced) in 2024-11 | Never treat the submission time as the release date; it is only the labelled `submission_only` fallback |
| Unknown ID → HTTP 200 with **zero entries** | `id_list=2401.99999` | Treated as not found (404 `source_not_found`) |
| Errors come as HTTP 200 with one entry whose `<id>` is `https://arxiv.org/api/errors` | `id_list=hep-th/9711200v2` (with `curl`) | Parsed as an error, never as a paper |
| Old-style IDs with a version suffix always fail: HTTP 500 when the `/` is percent-encoded (as httpx sends query parameters), HTTP 200 error entry when literal; also inside a multi-ID list | `hep-th/9711200v2`; `1706.03762,hep-th/9711200v2` | The client always queries **without** a version. Unversioned old-style IDs work with either encoding |
| Several IDs per request work (`id_list=a,b`) | `1706.03762,hep-th/9711200` → 2 entries | Batched up to 50 IDs per request |
| `<arxiv:doi>` and `<arxiv:journal_ref>` are author-supplied links to a published version | hep-th/9711200: `10.1023/A:1026654312961`, `Adv.Theor.Math.Phys.2:231-252,1998` | Decisive Version Matcher evidence (D29). Kept in the source record; **not** an identifier of the arXiv manifestation |
| `<arxiv:affiliation>` appears only when supplied | none in the samples | Stored when present |
| The arXiv DataCite DOI is `10.48550/arXiv.<id>` | — | Parsed as the arXiv ID of the same manifestation |

**Terms of use:** at most 1 request every 3 seconds, one connection at a time. Enforced across
API and worker processes by `source_rate_limits` (shared slot reservation).

**Caching:** entity lookups 12 h, searches 1 h. Every entry is stored in `source_records`
(source `arxiv_api`, entity id `<id>v<latest>`), once per distinct content.

## Announcement feeds (`https://rss.arxiv.org/rss/<category>`)

Client: `integrations/arxiv_feed.py`; capture job: `services/dates/announcements.py`.
Recorded feeds: `backend/tests/fixtures/sources/arxiv_rss/`. Verified on 2026-11-11:

| Behaviour | Evidence | Consequence |
|---|---|---|
| One RSS 2.0 feed per category, rebuilt once per announcement (`lastBuildDate` ~05:00 UTC), `skipDays` Saturday and Sunday, `Cache-Control: max-age` ~24 h, `ETag` | cs.DL, cs.LG, q-bio.QM | Daily worker job after 06:00 UTC (`ARXIV_CAPTURE_AFTER_UTC_HOUR`), once per UTC day (`jobs.dedupe_key`) |
| **No history**: only the latest announcement day | — | Days the job misses are lost; those papers keep their submission time or secondary dates |
| Channel and item `pubDate` = the announcement day at **midnight US Eastern** (`Wed, 11 Nov 2026 00:00:00 -0500`) | all items of a feed share it | The calendar date is the announcement day; stored as a date-only value (00:00 UTC, day precision, D23) |
| `arxiv:announce_type` ∈ `new`, `cross`, `replace`, `replace-cross`; `guid` = `oai:arXiv.org:<id>v<version>` | cs.LG: 134 new, 101 cross, 78 replace, 70 replace-cross | Logged exactly as listed in `arxiv_announcement_log` |
| `cross` / `replace-cross` can list **old** papers cross-listed later | `2109.05627v2` listed as `cross` on 2026-11-11 | Only `new` → `preprint_announced` (the work's first announcement) and `replace` → `version_announced` (that version); cross listings stay in the log |
| Submission and announcement differ | `2611.13190`: submitted 2026-11-09 20:10 UTC, announced 2026-11-11 | The announcement replaces the `submission_only` basis as the verified first appearance |
| Empty feeds exist on announcement days | math.HO: 0 items, `pubDate` 2026-11-11 | Recorded as fetched; nothing logged |

Categories captured: configured `ARXIV_ANNOUNCEMENT_CATEGORIES` plus the primary category of
every arXiv work in a project (until M1c maps categories from research objectives). Papers
ingested later receive announcements already in the log.
