# 6. Frontend design

## 6.1 Stack

Vite · React 18 · TypeScript (strict) · Tailwind CSS · React Router ·
TanStack Query (server state) · Zustand only for small UI state (panels,
selections) · Radix primitives with locally owned components (shadcn/ui
style) · TanStack Table (virtualised paper tables) · Cytoscape.js for the
citation/knowledge graph · `openapi-typescript` + a thin fetch wrapper for a
typed API client · Vitest + Testing Library · MSW for API mocking ·
Playwright for end-to-end tests.

## 6.2 Layout

```
┌───────────────────────────────────────────────────────────────────┐
│ Top bar: project switcher · global search · run status · settings │
├──────────┬────────────────────────────────────────┬───────────────┤
│ Sidebar  │ Main content (page)                    │ Right drawer  │
│ (nav)    │                                        │ (paper detail │
│          │                                        │  / evidence)  │
└──────────┴────────────────────────────────────────┴───────────────┘
```

The right drawer is shared: clicking any citation chip, paper row or evidence
link opens the paper or the exact quote without leaving the page.

## 6.3 Pages

| Page | Route | Phase | Purpose & key elements |
|---|---|---|---|
| Dashboard | `/` | 1 | Recent projects, running runs with progress, pending approvals, saved paper count, integration health |
| New Research Project | `/projects/new` | 1–2 | Topic/problem statement, optional keywords, include/exclude terms, sources, year range, limits, checkpoint preferences; "Start discovery" |
| Project overview | `/projects/:id` | 2 | Stats, run history, latest report, next suggested step |
| Run view | `/projects/:id/runs/:runId` | 2 | Live timeline (SSE), per-source status, checkpoint panels (query plan editor, paper set review), errors with reasons |
| Research Search | `/search` | 2 | Ad-hoc multi-source search; per-source result counts and failures; save to project |
| Literature Review (report) | `/projects/:id/report` | 2 → 6 | Milestone 1: discovery report (latest, foundational, related, search log, coverage). Later: full review with sections, claim badges, citation validation |
| Paper Explorer | `/projects/:id/papers` | 2 | Filterable table (role, year, source, OA, saved), citation graph tab, duplicates tab |
| Paper detail | drawer + `/papers/:id` | 2–3 | Metadata with per-field source, identifiers (DOI/arXiv links), provenance, references/citations, full-text status, extractions with quotes, code/HF links |
| Methodology Comparison | `/projects/:id/methods` | 4 | Taxonomy tree + comparison matrix; cells open evidence |
| Datasets & Benchmarks | `/projects/:id/datasets` | 3–5 | Dataset catalogue, metric catalogue, benchmark tables (reported values only, comparability flags, source quote on hover) |
| Research Gap Explorer | `/projects/:id/gaps` | 4 | Gap candidates with signal visualisations (intersection heatmap, recurring limitation clusters), probe results, status |
| Research Ideas | `/projects/:id/ideas` | 4 | Ranked hypotheses; score breakdown; red-team objections; novelty check details (queries, dates, nearest work) |
| Proposal Generator | `/projects/:id/proposals` | 4–6 | Choose hypotheses → experiment plan → proposal draft; validation panel; export |
| Saved Papers | `/saved` | 2 | Cross-project saved papers, tags, notes, BibTeX export |
| Research Knowledge Graph | `/projects/:id/graph` | 2 (citation graph) → 7 | Interactive graph; filter node types; click → drawer |
| Project History | `/projects/:id/history` | 2 | Runs, configs, checkpoint decisions, report versions; diff of paper sets between runs |

## 6.4 Core components

| Component | Responsibility |
|---|---|
| `AppShell`, `Sidebar`, `TopBar`, `ProjectSwitcher` | layout, navigation |
| `RunProgress` | subscribes to SSE, shows node timeline + per-source status chips |
| `CheckpointPanel` | generic container; renders `QueryPlanEditor` or `PaperSetReview` by checkpoint name |
| `QueryPlanEditor` | editable list of queries per source with rationale, add/remove, source toggles |
| `PaperTable` | virtualised table; columns configurable; bulk include/exclude/save |
| `PaperRow` / `PaperCard` | title, authors, venue/year, role badges with reason tooltip, identifier links, OA badge |
| `PaperDrawer` | detail view; tabs: Overview, Provenance, Citations, Full text, Extractions, Code |
| `IdentifierLinks` | DOI → doi.org, arXiv → arxiv.org/abs, S2, OpenAlex links |
| `ProvenanceBadge` | shows source(s) of a field with fetched-at timestamp |
| `CitationChip` | inline `[n]` that resolves to a project paper; never renders for unknown IDs |
| `ClaimBadge` | colour + label: **Reported** / **Extracted** / **AI hypothesis** / **AI synthesis** |
| `EvidenceQuote` | quote, page, section, "open in PDF" (highlights bbox via pdf.js) |
| `CoverageNotice` | lists failed sources, unavailable full texts, rate-limit truncation |
| `CitationGraph` | Cytoscape graph with role colouring and in-corpus degree sizing |
| `ComparisonMatrix`, `TaxonomyTree`, `BenchmarkTable`, `GapHeatmap`, `ScoreBreakdown`, `RedTeamPanel` | Phase 3–4 views |
| `ExportMenu` | Markdown/JSON/BibTeX/CSV (+ LaTeX/PDF later) |
| `EmptyState`, `ErrorState`, `ProblemDetails` | consistent display of RFC 7807 errors |

## 6.5 UX principles

- **Provenance is one click away** from any fact.
- **AI content is never unlabelled**; badges use both colour and text (accessible).
- **Partial results are first-class:** a run with one failed source still
  shows results, with a visible `CoverageNotice`.
- Keyboard navigation in tables and the drawer (j/k, enter, s to save, x to exclude).
- Dense but calm design: neutral palette, one accent colour, readable serif
  option for long-form reports; light/dark themes.
- Accessibility: WCAG 2.1 AA target, Radix primitives for focus management.

## 6.6 Frontend structure

```
frontend/src/
  app/          router, providers (QueryClient, theme), AppShell
  api/          generated types (openapi.d.ts), client.ts, sse.ts, query keys
  features/
    projects/   pages + components + hooks for projects
    runs/       RunProgress, CheckpointPanel, QueryPlanEditor, PaperSetReview
    papers/     PaperTable, PaperDrawer, IdentifierLinks, CitationGraph
    search/     ad-hoc search
    reports/    report viewer, ClaimBadge, CitationChip, ExportMenu
    saved/
    (later) analysis/, methods/, datasets/, gaps/, ideas/, proposals/, graph/
  components/ui/  buttons, dialogs, tables, badges, tooltips (design system)
  lib/          formatting (dates, authors), url builders, utilities
  test/         MSW handlers, fixtures, test utils
```
