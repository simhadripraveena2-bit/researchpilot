# 1. Requirements analysis

## 1.1 What the product must do

| Capability | Interpreted requirement | Phase |
|---|---|---|
| Latest research | Papers published within a configurable window (default 24 months), sorted by date, from arXiv / S2 / OpenAlex | 2 |
| Foundational & related papers | Foundational = heavily referenced *by the project's own paper set* and/or highly cited globally and older; related = relevant but neither latest nor foundational. Each classification stores its reason | 2 |
| Citation relationships | References and citations of seed papers (1 hop in M1, configurable depth with budget later); store edges with source and influence flag | 2 |
| Full-text retrieval | Find legal open-access PDFs, download, hash, store; record precise failure reason otherwise | 3 |
| Methods / architectures / algorithms / contributions | Typed extraction with evidence spans; normalised entity names | 3 |
| Datasets, benchmarks, metrics | Typed entities; reported results as (method, dataset, metric, value, setting) tuples with a mandatory evidence span | 3 |
| Implementations | GitHub repos and Hugging Face models/datasets/Spaces linked to papers, with link provenance (paper text, HF paper page, GitHub search match) | 5 |
| Limitations & open questions | Author-stated limitations extracted with evidence; inferred limitations labelled as such | 3 |
| Research problems & hypotheses | Produced by the gap pipeline (§4.6), never by one summarisation prompt | 4 |
| Novelty / feasibility / significance | Scored with component breakdowns and the evidence/searches behind each score | 4 |
| Experimental plans & proposals | Generated from surviving hypotheses + dataset/metric catalogue | 4, 6 |
| Literature reviews with citations | Rendered from the research record; every sentence that makes a factual claim carries at least one citation to a project paper | 6 |

## 1.2 Non-functional requirements

- **Traceability:** claim → evidence span → document (page, section, char
  offsets) → paper → source record (raw API response, retrieval time).
- **No fabrication:** enforced structurally (DB-sourced citations, verified
  quotes, schema validation), not only via prompts.
- **Reproducibility:** run manifests; cached raw responses; versioned prompts.
- **Resilience:** per-source rate limits, retries with backoff + jitter,
  `Retry-After` handling, circuit breakers; partial results are allowed and
  labelled.
- **Modularity:** agents are plain async functions/classes with typed
  input/output and injected dependencies; LangGraph only wires them together.
- **Testability:** unit tests with recorded API fixtures and a fake LLM;
  integration tests against Postgres in Docker; opt-in live tests.
- **Security:** API keys only from environment; never logged; no user data
  sent to third parties beyond the search queries themselves (and the
  contact email required by polite-pool APIs, which is configurable).

## 1.3 Explicit non-goals (for now)

- Scraping Google Scholar or any site whose terms forbid it.
- Bypassing paywalls or using shadow libraries.
- Fully autonomous runs with no human checkpoints (checkpoints can be set to
  auto-approve per project, but defaults are on).
- Multi-tenant SaaS concerns (billing, org management).
- Real-time collaboration.

## 1.4 Key risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Source rate limits (esp. Semantic Scholar without a key) | Slow or partial discovery | Token buckets per source, cache, batch endpoints, request an S2 API key, degrade gracefully and report coverage |
| Inconsistent metadata across sources (titles, years, preprint vs published) | Duplicates or wrong merges | Identifier-first dedup, conservative fuzzy merge with thresholds, keep all source records, manual merge/split in UI |
| Missing abstracts (publisher restrictions) | Weak ranking | Combine sources (S2, OpenAlex inverted index, Crossref JATS, arXiv); mark `abstract_available=false` and rank on title |
| LLM hallucinated quotes / citations | Untrustworthy output | Quote verification, ID-constrained references, schema validation, red-team agent, evaluation set |
| PDF extraction errors (tables, two-column layouts) | Wrong results extracted | GROBID TEI with coordinates; results require a table/text evidence span and are shown with the quote for human checking |
| Citation counts differ by source | Misleading "foundational" scores | Store count + source + as-of date; use in-corpus reference counts as the main signal |
| Scope creep | Never ships | Phase gates with acceptance criteria; Milestone 1 is narrow and end-to-end |
| Licensing (PyMuPDF AGPL, Neo4j GPL, CC-BY-SA dumps) | Legal exposure | Decision D2, documented licences per dependency |
