# ResearchPilot

Autonomous literature review and research discovery platform.

**From Research Beginner to Research Creator** — a persistent research
companion across DISCOVER → LEARN → UNDERSTAND → COMPARE → INVESTIGATE →
VALIDATE → INNOVATE.

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
| 9 | [Roadmap & acceptance criteria](docs/plan/09-roadmap.md) | Phases, Milestone 1 spec, acceptance criteria (ordering superseded by 14) |
| 10 | [Product requirements v2](docs/plan/10-product-requirements.md) | Vision, personas, requirements by journey stage, claim taxonomy, UX |
| 11 | [Architecture v2](docs/plan/11-architecture-v2.md) | Review of v1, extensibility decisions, schema and agent changes |
| 12 | [User journeys](docs/plan/12-user-journeys.md) | Beginner, advanced and intermediate journeys |
| 13 | [Competitive differentiation](docs/plan/13-competitive-differentiation.md) | Strengths of existing tools and where ResearchPilot differs |
| 14 | [MVP & roadmap v2](docs/plan/14-mvp-and-roadmap.md) | Prioritisation, MVP scope and acceptance criteria, releases R0–R5 |
