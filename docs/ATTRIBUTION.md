# Data sources and attribution

ResearchPilot shows data from external scholarly sources. This page records each source's
attribution requirement and where the ResearchPilot website must show it. Source-specific
details are in `docs/integrations/`.

## Semantic Scholar (required)

Requirements (API License Agreement, <https://api.semanticscholar.org/license>, read
2026-11-11):

1. Any public use of Semantic Scholar data points back to
   `https://www.semanticscholar.org/?utm_source=api` (the `utm_source=api` parameter on every
   link to Semantic Scholar).
2. The **Semantic Scholar name and logo** appear on any public display of the data. Use the
   official logo asset and AI2's branding guidelines (not yet added to the repository; obtain
   them from Semantic Scholar before the first public release).
3. Data made publicly available credits Semantic Scholar according to standard scientific
   practice. In publications and reports, cite the Semantic Scholar Open Data Platform:
   Kinney et al., *The Semantic Scholar Open Data Platform*, arXiv:2301.10140 (2023).

Attribution text: **"Data from Semantic Scholar"** with the logo, linking to
`https://www.semanticscholar.org/?utm_source=api`.

### Where it must appear in the ResearchPilot website

| Place | What | When |
|---|---|---|
| Global footer of every page that shows paper data | Logo + "Data from Semantic Scholar" link (`utm_source=api`) | Always while Semantic Scholar data can appear on the page |
| Paper detail page, source/provenance panel | "Semantic Scholar" entry with a link to the paper's page `https://www.semanticscholar.org/paper/{paperId}?utm_source=api`, next to the identifiers, dates and links it contributed (e.g. a `reported_publication_date` row reported by `semantic_scholar`) | When the work has a Semantic Scholar source record |
| Version/match evidence ("Possibly the published version of …") | Name the source of strong evidence: "Listed together by Semantic Scholar" with the link | When a match decision cites a Semantic Scholar listing |
| Search, discovery and Latest Research result lists, citation counts, reference lists | Source badge "Semantic Scholar" on values it supplied, with the link | When a displayed value came from Semantic Scholar |
| Exports and reports (CSV, BibTeX, Markdown/PDF reports, share pages) | Attribution line "Includes data from Semantic Scholar (https://www.semanticscholar.org/?utm_source=api)" and the citation above | Whenever exported data includes Semantic Scholar fields |
| About / Data sources page | Full credit, logo, licence summary, the citation above | Always |

The API response provenance needed for this is already stored: every Semantic Scholar value
is linked to its `source_records` row (`source = semantic_scholar`).

### Licence scope

The standard API licence covers internal, non-commercial research and educational use. A
publicly hosted ResearchPilot, or any commercial use, may need Semantic Scholar's expanded
licence; confirm the licensing position before gate H / any hosted deployment. (This is a
note for the project owner, not legal advice.)

## Other sources (to confirm before a public release)

The other integrations (arXiv, bioRxiv/medRxiv, Crossref, OpenAlex) are already shown with
their names in each date's provenance. Their attribution and terms-of-use requirements will
be recorded here in the same form before any public release.
