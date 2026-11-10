# ResearchPilot

Autonomous literature review and research discovery platform.

ResearchPilot takes a research topic or problem statement and runs an
evidence-first workflow: discover papers across academic sources, deduplicate
them, explore citations, analyse full texts, surface datasets / benchmarks /
metrics, find research gaps, challenge candidate hypotheses with a red-team
reviewer, and produce reports in which every claim traces back to a paper (and,
where possible, a page or section).

**Status:** planning. No application code has been written yet. The plan is
awaiting approval.

## Planning documents

| # | Document | Contents |
|---|----------|----------|
| 0 | [Plan index & open decisions](docs/plan/00-index.md) | Summary, guiding principles, decisions needed before coding |
| 1 | [Requirements analysis](docs/plan/01-requirements-analysis.md) | Interpreted requirements, non-goals, risks |
| 2 | [System architecture](docs/plan/02-system-architecture.md) | Components, runtime topology, cross-cutting concerns |
| 3 | [Database schema](docs/plan/03-database-schema.md) | PostgreSQL schema, Qdrant collections, Neo4j model |
| 4 | [Agents & LangGraph workflows](docs/plan/04-agents-and-workflows.md) | Agent contracts, shared state, graphs, checkpoints, gap pipeline |
| 5 | [API endpoints](docs/plan/05-api.md) | REST + SSE API, by phase |
| 6 | [Frontend](docs/plan/06-frontend.md) | Pages, components, state management |
| 7 | [Repository structure](docs/plan/07-repository-structure.md) | Folder layout, tooling |
| 8 | [External APIs](docs/plan/08-external-apis.md) | Each integration, its limits and failure modes |
| 9 | [Roadmap & acceptance criteria](docs/plan/09-roadmap.md) | Phases, Milestone 1 spec, acceptance criteria |
