# 0. Plan index, principles and open decisions

## Summary

ResearchPilot is a research workspace, not a chatbot. Its core asset is a
**provenance-tracked research record**: papers (deduplicated across sources),
the raw source responses they came from, full-text documents, evidence spans
(quoted text with page/section), typed extractions, and claims that link back
to evidence. Agents read and write that record; reports are rendered from it.

The first working milestone (Phases 1 + 2) is a complete, LLM-optional
paper-discovery workflow:

> topic → query plan (human approval) → search arXiv + Semantic Scholar +
> OpenAlex → normalise + deduplicate → enrich metadata/abstracts → one-hop
> citation/reference expansion → rank and classify (latest / foundational /
> related) → human review → persist → cited paper report.

## Guiding principles

1. **Evidence before prose.** Anything shown to the user is either (a) source
   metadata with a recorded origin, (b) a quote/extraction with a located
   evidence span, or (c) an explicitly labelled AI-generated synthesis or
   hypothesis that references (a) or (b).
2. **Three claim kinds, always visible:** `reported_result` (a number or
   statement the paper's authors report), `extracted_observation` (something
   the system extracted or computed from the papers), `ai_hypothesis` /
   `ai_synthesis` (model-generated). The UI colour-codes them; exports label
   them.
3. **Citations come from the database, never from the model.** LLM outputs
   refer to papers by internal IDs that must already exist in the project's
   paper set. A Pydantic validator rejects unknown IDs. Reference lists are
   rendered from stored metadata only.
4. **Quotes are verified mechanically.** Every LLM extraction must include a
   verbatim quote; the system checks the quote exists (after whitespace/
   hyphenation normalisation) in the source text and records its page and
   character offsets. Unverifiable extractions are dropped and logged, not
   shown.
5. **Honest failure.** A source that times out, a PDF behind a paywall, an
   empty search: each is recorded with a reason code and shown in the report's
   "coverage and limitations" section. Nothing is reported as retrieved or
   verified unless it was.
6. **Reproducible runs.** A run stores its config, generated queries, raw
   source responses (hashed), prompt versions, model IDs and code version, so
   it can be audited and replayed from cache.
7. **Deterministic where possible, LLM where useful.** Deduplication, citation
   expansion, ranking, "foundational" detection and gap *candidate* detection
   are algorithmic and explainable. LLMs are used for query expansion,
   extraction from text, clustering labels, hypothesis wording and critique.
8. **Never claim guaranteed novelty.** Novelty results are phrased as
   "no closely matching work found in these N searches across these sources on
   this date", with the searches listed.

## Decisions needed before implementation

These are the choices I'd like you to confirm or change. My recommendation is
listed first.

| # | Decision | Recommendation | Alternatives |
|---|----------|----------------|--------------|
| D1 | LLM provider | Provider-agnostic `LLMGateway` interface; first implementation uses the Anthropic SDK with `claude-opus-5-5` for every agent, model configurable per agent via env | OpenAI, local models via an adapter. Per-agent cheaper models (e.g. `claude-sonnet-5-5` / `claude-haiku-5-5` for bulk extraction) are a cost decision for you to make after we measure quality |
| D2 | PDF text library | **PyMuPDF is AGPL-3.0.** If ResearchPilot will ever be offered as a network service without releasing its source, that is a licensing problem. Recommend: GROBID (Apache-2.0) as primary, `pypdfium2` (Apache/BSD) as fallback, PyMuPDF behind an optional adapter | Use PyMuPDF and accept AGPL / buy an Artifex commercial licence |
| D3 | Job execution | Separate worker process; Redis for job queue (arq), shared rate-limit buckets and progress pub/sub; LangGraph Postgres checkpointer for durable, resumable runs | Postgres-only queue (`SKIP LOCKED`) to avoid Redis; in-process background tasks (not durable) |
| D4 | Embeddings | Local `sentence-transformers` model (e.g. a SPECTER2 / general-purpose MiniLM-class model) so retrieval works without paid APIs | Hosted embedding API |
| D5 | Auth / multi-user | Single-user local deployment first; `user_id` column on owned tables from day one so auth can be added in Phase 7 | Auth from Phase 1 |
| D6 | Google Scholar | **Not integrated.** No official API and its terms forbid automated scraping. Coverage gap is filled by OpenAlex + Semantic Scholar + Crossref | — |
| D7 | Papers with Code | **Not available as a live service** (sunset in 2025, now redirects to Hugging Face). Use Hugging Face Papers/Hub links + GitHub search for code discovery; optionally import an archived PwC data dump as a frozen, dated snapshot (licence CC-BY-SA) | Drop PwC entirely |
| D8 | Full-text sources | arXiv PDFs, Semantic Scholar `openAccessPdf`, OpenAlex `best_oa_location`, plus **Unpaywall** (not in your list; strongly recommended, free with an email) | Without Unpaywall, OA coverage drops noticeably for non-arXiv papers |
| D9 | Python tooling | `uv` + Python 3.12, `ruff`, `mypy --strict` on core packages, `pytest` | Poetry |
| D11 | OpenAlex access | OpenAlex has required an API key since Feb 2026, and usage is metered (a free daily allowance, then paid). Recommend: get a free key and set a per-day usage budget in config; the run marks OpenAlex `budget_exhausted` instead of failing | Disable OpenAlex by default and rely on S2 + arXiv + Crossref |
| D10 | Frontend tooling | Vite + React 18 + TypeScript + Tailwind + TanStack Query + React Router; UI primitives from Radix (shadcn/ui-style, copied in); OpenAPI-generated TS client | Next.js (unnecessary — no SSR need) |

## Document map

1. [Requirements analysis](01-requirements-analysis.md)
2. [System architecture](02-system-architecture.md)
3. [Database schema](03-database-schema.md)
4. [Agents & LangGraph workflows](04-agents-and-workflows.md)
5. [API endpoints](05-api.md)
6. [Frontend](06-frontend.md)
7. [Repository structure](07-repository-structure.md)
8. [External APIs](08-external-apis.md)
9. [Roadmap & acceptance criteria](09-roadmap.md)

API facts in document 8 (rate limits, quotas, terms) reflect my knowledge as of
planning and **must be re-verified against each provider's current docs** when
that integration is implemented; the integration's README will record the date
it was verified.
