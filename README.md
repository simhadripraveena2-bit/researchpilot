# ResearchPilot

Autonomous literature review and research discovery platform.

**From Research Beginner to Research Creator** — a persistent research
companion across DISCOVER → LEARN → UNDERSTAND → FILTER → COMPARE →
INVESTIGATE → VALIDATE → EXPERIMENT → PROPOSE.

ResearchPilot takes a research topic or problem statement and runs an
evidence-first workflow: discover papers across academic sources, deduplicate
them, explore citations, analyse full texts, surface datasets / benchmarks /
metrics, find research gaps, challenge candidate hypotheses with a red-team
reviewer, and produce reports in which every claim traces back to a paper (and,
where possible, a page or section).

Two recurring tools sit across the journey:

- **Latest Research:** a dedicated page showing what was released in your
  area in the last 7 days (adjustable). Sources include arXiv, bioRxiv/medRxiv,
  Semantic Scholar, OpenAlex and Crossref. Every paper has a provenance-tracked
  date and a release type. Each relevant paper gets an eight-question brief
  ending in read now / save for later / deprioritise, never ranked by recency.
- **Ask & Learn:** a research tutor that knows your project and the paper you
  are reading. It explains at your level and in your preferred style, teaches
  concepts step by step with short understanding checks, tracks learning
  progress per project, and cites passages or labels background knowledge.

**Status:** planning. No application code has been written yet. The plan is
awaiting approval.

## Documentation (canonical)

| Document | Contents |
|---|---|
| [Product requirements](docs/PRODUCT_REQUIREMENTS.md) | Vision, users, requirements per journey stage, evidence rules |
| [Architecture](docs/ARCHITECTURE.md) | Principles, topology, modules, weaknesses fixed, external dependencies, costs, free operation |
| [Research Intelligence Engine](docs/RESEARCH_INTELLIGENCE_ENGINE.md) | Objective-aware usefulness: dimensions, signals, scoring, cards, verification, overrides, recent items |
| [Database schema](docs/DATABASE_SCHEMA.md) | All tables by release |
| [Agent design](docs/AGENT_DESIGN.md) | LLM agents vs. deterministic services, workflows, checkpoints |
| [User experience](docs/USER_EXPERIENCE.md) | Journey bar, levels, cards, Latest Research page, Ask & Learn panel, error states, journeys, navigation |
| [Competitive analysis](docs/COMPETITIVE_ANALYSIS.md) | Existing tools and how ResearchPilot differs |
| [Implementation roadmap](docs/IMPLEMENTATION_ROADMAP.md) | Audit, dependency graph, releases R0–R5, tasks, acceptance tests, risks, decisions |
| [Evaluation framework](docs/EVALUATION_FRAMEWORK.md) | Gold sets, metrics, release gates |

Earlier planning rounds are kept for history in [docs/plan/](docs/plan/00-index.md).
