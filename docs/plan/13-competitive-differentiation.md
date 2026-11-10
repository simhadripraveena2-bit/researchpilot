# 13. Competitive differentiation analysis

> Based on publicly described capabilities of each product as I know them at
> planning time. Product features change quickly; this table must be
> re-checked against each product's current site before being used in any
> external material, and should not be quoted as a statement of fact about
> competitors.

## 13.1 What each product does well

| Product | Main strength | What we learn from it | What it does not try to be |
|---|---|---|---|
| **Elicit** | Structured data extraction from papers into tables; screening and systematic-review workflows; sentence-level source quotes | Tables with a quote behind each cell are the right unit for comparison | A learning environment for newcomers; a persistent gap/idea tracker across months |
| **Undermind** | Deep, agentic, high-recall search for specific and niche questions; explains why papers match | Iterative search that adapts to what it finds; recall matters more than speed for research | A reading/learning tool or an analysis workspace over a long-lived project |
| **Semantic Scholar** | Large open scholarly graph; TLDR summaries; Semantic Reader with in-context citation cards and term definitions; research feeds | Explanation in the reading context; open data via API | Cross-paper synthesis for a user's project; gap discovery |
| **ResearchRabbit** (and Connected Papers-style tools) | Visual citation-network exploration; collections; alerts | Visual maps make a field approachable; collections + alerts create habit | Content-level analysis (methods, results, limitations) with evidence |
| **scite** | Citation statements classified as supporting / contrasting / mentioning | Showing evidence *against* a claim, not only for it | Learning, field mapping, idea generation |
| **SciSpace** | Reading copilot: explains passages, equations, tables in a PDF; literature review tables | Explaining exactly what the user is looking at, at their level | A project-wide learning path tied to a mapped field; adversarial idea validation |
| **Hugging Face** (Hub, Papers pages) | Models, datasets, Spaces linked to papers; community trending papers | Implementation and dataset availability is a key feasibility signal | Literature analysis |
| *(Papers with Code — discontinued 2025)* | Benchmarks and leaderboards linked to code | Benchmark tables are valuable, but scraped leaderboards go stale and lack context | — |

## 13.2 Where ResearchPilot is different

ResearchPilot should not try to beat these tools at their single strength
(index size, search recall, citation-statement classification at web scale).
It wins by connecting the stages they leave separate:

| Differentiator | How it shows up | Why others don't do this (structurally) |
|---|---|---|
| **1. One persistent, connected project record** | Papers found in DISCOVER are the papers explained in LEARN, compared in COMPARE, mined for gaps in INVESTIGATE, and monitored later | Most tools are organised around a search, a paper or a table, not a long-lived project that accumulates decisions |
| **2. Learning path built from *your* field's actual papers** | Primer, glossary and reading order come from the surveys and foundational papers discovered for this topic, and progress is tracked | Reading copilots explain one paper; maps show structure; neither produces an ordered curriculum from the mapped field |
| **3. Level-adaptive everything, same evidence** | Switch beginner ↔ advanced on any explanation, table or map; evidence is identical | Tools usually target one audience (experts or students) |
| **4. Visible claim kinds everywhere** | Reported / Extracted / AI explanation / Hypothesis badges on every block, exported too; background explanations explicitly marked as unsourced | Most tools show citations but don't separate reported findings from AI interpretation consistently |
| **5. Gap detection from computed signals, with evidence for *and* against** | Recurring limitations across independent groups, sparse intersections, conflicts; each gap gets overlap and contradiction searches | Gap suggestions elsewhere are typically LLM summaries of a paper set |
| **6. Adversarial validation of ideas** | Separate red-team agent with its own searches; novelty phrased with search record and date | — |
| **7. From idea to experiment** | Baselines, metrics, protocols and compute only from reported data; implementations linked | Benchmark data and literature analysis live in different products |
| **8. A project that notices change** | Impact alerts when a new paper overlaps an open gap, an accepted idea or a running experiment | Alerts elsewhere are usually "new papers matching a query", not "this paper affects your idea" |

## 13.3 Where we are deliberately weaker (and how we handle it)

| Area | Reality | Mitigation |
|---|---|---|
| Index size and freshness | We depend on arXiv, Semantic Scholar, OpenAlex, Crossref | Combine sources; show coverage per source in every report |
| Full text | Open access only, plus user uploads | Clear unavailable reasons; abstract-only labelling |
| Search recall on niche questions | A first version won't match a dedicated deep-search product | Citation expansion + user-pinned seeds; iterative search later |
| Citation-statement classification at scale | We only have citation contexts and intents that S2 provides, plus our own full-text analysis | Use them where available; never claim more coverage than we have |
| Systematic-review compliance (PRISMA etc.) | Not an MVP goal | Decision log and search log make it feasible later |

## 13.4 Positioning statement (draft)

> Other tools help you search, read, or extract. ResearchPilot stays with
> your project from the first unfamiliar term to a tested research idea —
> and shows you the evidence for every step.
