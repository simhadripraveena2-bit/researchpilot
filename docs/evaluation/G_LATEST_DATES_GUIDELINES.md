# G-LATEST-DATES annotation guidelines (g-latest-dates-guidelines-v0.1)

Status: **draft v0.1**. B0 labels in `backend/benchmarks/g_latest_dates/b0.json` are
AI-proposed (`ai_proposed`) and not gold until reviewed against the primary pages.

## Unit of annotation

A **work**, given as one or more identifiers ingested in order (several identifiers = the
versions of one work), optionally with the arXiv announcement feeds captured for the
recorded day.

## Fields per case

| Field | Meaning |
|---|---|
| `id` | Stable ID `GD-<split>-NNN`. |
| `identifiers` | The work's identifiers (system-of-record records define it). |
| `capture_feeds` | arXiv RSS categories whose recorded feed is captured after ingestion. |
| `expected.first_public_date` / `basis` | The first public appearance **the system may state**, and its event basis (`announced`, `posted`, `published_online`, `issue`, `issued`, `submission_only`). `null` if no date may be stated. |
| `expected.confidence` | `verified`, `corroborated`, `source_agreement`, `single_source`, `conflicting` or `uncertain` (ARCHITECTURE §4.8.3). |
| `expected.first_public_kind` | Which manifestation the first date belongs to (`preprint`, `published`, `other`). |
| `expected.candidate_public_date` | An unconfirmed date the system may show only as unconfirmed. |
| `expected.window`, `expected.release_type` | Optional: a window and the release type the work must get in it (`none` = not listed). |
| `explanation`, `evidence` | Event types, sources and values relied on, with provenance. |

## Rules

1. **First public appearance** is the earliest public-availability event of any version
   (announcement or posting, online publication, issue, Crossref `issued`). Submission,
   acceptance, `created`, `deposited` and `indexed` dates are not public availability.
2. **Never use a journal date as first public when an earlier preprint of the same work
   exists.** A journal version of an older preprint has the preprint's date.
3. arXiv: the **announcement** (captured `new` feed entry) is the public date. Without a
   captured announcement, the v1 submission is stated as `submission_only`. It is verified
   as a submission, never as a release date. Cross-listings (`cross`, `replace-cross`) are
   not announcements of the work. A `replace` entry announces a revision, not a new work.
4. bioRxiv/medRxiv: the server's v1 posting date (API) is primary; Crossref's `posted` date
   for the same DOI is secondary.
5. `verified` needs a primary (system-of-record) event at day precision. Month- or year-only
   dates are `uncertain`. Primary events of one kind more than 2 days apart are
   `conflicting`.
6. A day-01 print/issue date is the issue's **nominal** date (month precision), not a day of
   public availability: an article is not in an issue before it is online.
7. Aggregator dates (OpenAlex `publication_date`, S2 `publicationDate`) are secondary claims.
   OpenAlex dates can be reduced in precision or be index dates. They never verify a date.
8. **Newly indexed is not newly released:** an old work ingested today is
   `newly_indexed_older` for today's window, never new research.

## Notes on labelling

- `first_public_kind` is set only when a first public date is expected.
- Where the documented policy can only state less than the truth (for example, an arXiv
  paper whose announcement feed was not captured), the case expects the policy's honest output
  and the explanation says so. Recall gaps of this kind are listed in the report's
  limitations; they are not scored as correct dates.

## Change log

- v0.1: GD-B0-041/042 first expected `first_public_kind = preprint` although no first public
  date is expected. Corrected under the note above; no system change.
- v0.1: GD-B0-034..036 (nominal issue dates) failed on the first run. The system was changed
  (R1_M1A_NOTES decision 70); the labels were not.

## Review procedure

As for G-MATCH: check the arXiv abstract page (submission history), the preprint-server page
(posting history) and the publisher page (online/issue dates), then set `team_reviewed`.
B1–B3 need `expert_adjudicated`.
