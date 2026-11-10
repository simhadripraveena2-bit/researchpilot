# Competitive Analysis

**Status:** canonical. It consolidates `docs/plan/13`.

> This is based on publicly described capabilities as I know them at
> planning time. Products change quickly. Re-check each product's current
> site before using any of this externally, and do not quote it as a
> statement of fact about competitors.

## 1. What existing tools do well

| Product | Main strength | Lesson for ResearchPilot | Outside its focus |
|---|---|---|---|
| **Elicit** | Structured extraction into tables with supporting quotes; screening and systematic-review workflows | A table cell with a quote behind it is the right unit for comparison | Teaching newcomers; long-lived gap and idea tracking |
| **Undermind** | Deep, iterative, high-recall search for specific questions; explains why papers match | Adaptive search and match explanations matter more than raw speed | Reading/learning; analysis workspace over months |
| **Semantic Scholar** | Large open scholarly graph; TLDRs; Semantic Reader with in-context citation cards and definitions; feeds | Explain in the reading context; open data | Synthesis across a user's project; gap discovery |
| **ResearchRabbit** / Connected-Papers-style tools | Visual citation-network exploration; collections; alerts | Maps make a field approachable; collections and alerts create habit | Content-level evidence (methods, results, limitations) |
| **scite** | Citation statements classified as supporting / contrasting / mentioning | Show evidence against, not only evidence for | Learning, filtering by objective, idea validation |
| **SciSpace** | Reading copilot explaining passages, equations and tables; literature tables | Explain exactly what the user is looking at, at their level | Curriculum across a mapped field; adversarial idea validation |
| **Hugging Face** | Models, datasets, Spaces, paper pages linking them | Implementation and dataset availability is a key feasibility signal | Literature analysis |
| *(Papers with Code, discontinued 2025)* | Benchmarks and leaderboards linked to code | Benchmark tables help, but scraped leaderboards go stale and lose context | — |

## 2. Gaps across the market

1. **Relevance is mostly one-dimensional.** Tools rank by "match to query",
   citations or recency. Few say *how* an item is useful (to learn from, as a
   baseline, as a dataset, as prior work that threatens novelty) or what is
   missing to judge it.
2. **Stages are separate products.** Search, reading, extraction, mapping and
   alerting live in different tools without shared memory of decisions.
3. **One audience.** Tools target either experts or students, rarely both on
   the same evidence.
4. **AI output and source facts are often blended.** Citations appear, but
   reported findings, extracted observations and AI interpretation are rarely
   separated consistently.
5. **Gap suggestions are summaries.** They are seldom computed from signals,
   and seldom tested against contradicting or overlapping work.

## 3. ResearchPilot's differentiators

| # | Differentiator | Concretely |
|---|---|---|
| 1 | **Objective-aware usefulness (RIE)** | Five dimensions, tiers, role tags and six-question cards for papers, methods, datasets, benchmarks, metrics, models, repos, gaps and ideas. Never date- or citation-only. Overridable |
| 2 | **One persistent, connected record** | The same items flow from DISCOVER to PROPOSE; decisions and overrides are remembered |
| 3 | **Learning built from your field** | Primer, glossary and reading path come from the project's surveys and foundational papers, chosen by the RIE learning-resource role |
| 4 | **Level-adaptive, same evidence** | Beginner ↔ advanced on any explanation, card, map or table |
| 5 | **Typed claims everywhere** | Reported / Extracted / AI explanation / Hypothesis badges in the UI and exports; background explanations explicitly unsourced |
| 6 | **Evidence for and against** | Gaps get overlap and contradiction probes; strong statements on cards are checked for counter-evidence |
| 7 | **Adversarial validation** | Independent novelty searches + red-team; novelty stated as a dated search record |
| 8 | **Idea → experiment** | Baselines, datasets, metrics, protocols and repos assessed for the user's constraints; compute only from reported data |
| 9 | **A project that notices change** | Impact alerts when new work affects open gaps, accepted ideas or experiments |
| 10 | **Free-source core** | Discovery, filtering, mapping and reading work without paid APIs |

## 4. Where we are deliberately weaker

| Area | Reality | Mitigation |
|---|---|---|
| Index size and freshness | Depends on arXiv, Semantic Scholar, OpenAlex, Crossref | Combine sources; show per-source coverage |
| Full text | Open access + user uploads only | Precise unavailable reasons; abstract-only labels |
| Niche-query recall (first versions) | Below dedicated deep-search tools | Citation expansion, pinned seeds, iterative search later |
| Citation-statement classification at scale | Limited to Semantic Scholar contexts/intents + our full-text analysis | Never claim wider coverage |
| Systematic-review compliance (PRISMA) | Not an MVP goal | Search and decision logs make it feasible later |

## 5. Positioning statement (draft)

> Other tools help you search, read or extract. ResearchPilot tells you what
> matters for *your* research question and why. It teaches you what you need
> to understand it, and stays with your project from the first unfamiliar term
> to a tested research idea, with evidence for every step.
