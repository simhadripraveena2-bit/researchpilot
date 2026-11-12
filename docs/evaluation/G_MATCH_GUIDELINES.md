# G-MATCH annotation guidelines (g-match-guidelines-v0.1)

Status: **draft v0.1**, written before B1 annotation (EVALUATION_FRAMEWORK §2b). The B0 labels
in `backend/benchmarks/g_match/b0.json` were pre-annotated against this draft by an AI
assistant (`ai_proposed`). They are **not gold** until a team member reviews each one against
the primary pages.

## Unit of annotation

A **pair of identifiers** (DOI, arXiv ID, ...). Each identifier stands for the record that its
system of record returns (arXiv API, bioRxiv/medRxiv API, Crossref). Annotators check the
public pages (arXiv abstract page, preprint-server page, publisher landing page). An
aggregator (OpenAlex, Semantic Scholar) can point annotators to evidence but is never enough
on its own.

## Fields per case

| Field | Meaning |
|---|---|
| `id` | Stable ID `GM-<split>-NNN`. Never reused, even when a case is retired. |
| `a`, `b` | The two identifiers. |
| `category` | One of the categories below. |
| `adversarial` | `true` if a naive title/author matcher would wrongly merge the pair. |
| `expected.relationship` | Ground truth: `same_work`, `related_not_same` or `different`. |
| `expected.outcome` | The **correct matcher output given the evidence in the records**: `auto_match`, `possible_match`, `related_not_same` or `no_match`. |
| `expected.auto_merge_allowed` | `true` only for `auto_match`. |
| `expected.user_confirmation_required` | `true` for `possible_match`: the pair stays apart until a user confirms. |
| `expected.decisive_evidence` | `true` if a record states an explicit link between the two identifiers. |
| `explanation`, `evidence` | Why the label holds, quoting the record fields. |
| `labels` | Who proposed, reviewed, adjudicated and approved the label, and the guideline version. |

## Relationship (ground truth)

- **same_work**: one scholarly work in different manifestations: preprint and journal
  version, preprint versions, the same paper in two printings, a reviewed preprint and its
  version of record. A retitled journal version is still the same work.
- **related_not_same**: linked but distinct items: comment or reply and its target,
  erratum, correction or retraction notice and the article, a supplement or component and
  its article, a peer-review document and the paper, a follow-up or extension.
- **different**: unrelated works, including identical or near-identical titles by other
  authors, and Part I vs Part II.

## Expected outcome (what the matcher should do)

1. A **decisive** explicit link (`is-preprint-of` / `has-preprint`, bioRxiv/medRxiv
   "published" DOI, arXiv author-supplied DOI) between two same-work records → `auto_match`.
2. A **strong** stated link (`is-same-as`, `is-version-of`, `has-version`, an aggregator
   record listing both identifiers) with matching title and authors → `auto_match`.
3. Same work, but no stated link → `possible_match`, however obvious it looks (identical
   title and authors, consecutive DOIs). Only a user may merge.
4. related_not_same with a stated comment/reply/correction/retraction link →
   `related_not_same`. Without such a link → `no_match` (keeping them apart is correct; the
   matcher can't type the relationship).
5. different → `no_match`. A merge here is a **false-positive merge**, the most serious
   failure.

The expected outcome uses only the evidence the system can see in the configured benchmark
run: systems of record plus recorded aggregator responses. If an aggregator is not consulted
(for example S2 without a key), its evidence doesn't count. The case's `evidence` lists the
fields relied on.

## Categories

`preprint_journal`, `preprint_versions`, `similar_title_different`, `part_series`,
`explicit_link_different_title`, `comment_reply`, `correction_notice`, `related_extends`,
`ambiguous_no_link`.

## Review procedure (B0 → `team_reviewed`)

1. Open both primary pages; confirm titles, authors, dates and any stated link.
2. Confirm or correct `relationship` and `outcome`; record the reason in `explanation`.
3. Set `labels.status = team_reviewed` and `labels.annotators = [<handle>]`.

For B1–B3: two independent annotators, adjudication of disagreements, evaluation-lead
approval, then `expert_adjudicated` (enforced by `guard_split`).

## Change log

- v0.1: first draft. Label correction during B0 preparation: GM-B0-012 first named the ATMP
  DOI, but the arXiv record of hep-th/9711200 carries the IJTP DOI. The case now uses the
  IJTP DOI and the ATMP pair is an `ambiguous_no_link` case. This was corrected from the
  record's own evidence, not from the matcher's output.
- v0.1: GM-B0-023 (1706.03762 ↔ 10.65215/pc26a033) was first drafted as an unlinked possible
  match. The recorded OpenAlex work for the arXiv paper lists the copy's DOI among its
  locations, which is a strong link under rule 2, so it was relabelled `auto_match` (category
  `preprint_versions`). It was found because the matcher merged the pair. The relabel follows
  the record's evidence and rule 2; neither the rule nor any threshold was changed.
