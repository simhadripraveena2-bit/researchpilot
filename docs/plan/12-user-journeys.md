# 12. User journeys

Two primary journeys (beginner and advanced) plus an intermediate variant.
Each step names the screen, what the user sees, what happens underneath, and
which release delivers it. Topics are illustrative.

## 12.1 Beginner journey — "I've been told to look into this and I don't know where to start"

**Persona:** second-year undergraduate, first research project. **Topic:** "graph neural networks for drug discovery".
**Level:** New to it. **Objective:** Learn the field.

| # | Stage | What the user does / sees | Underneath | Release |
|---|---|---|---|---|
| 1 | Start | Types the topic, picks "New to it" and "Learn the field", clicks **Start** | Project created with audience profile | R1 |
| 2 | DISCOVER | Sees: "I'll look for papers about *graph neural networks* applied to *drug discovery*, including surveys and classic papers. Look OK?" with the search phrases as editable chips. Clicks **Looks good** | Planner + `approve_query_plan` checkpoint in plain language | R1 |
| 3 | DISCOVER | Progress card: "Searching 3 sources… 214 papers found, 61 after removing duplicates… following references of the 15 most relevant papers…" | Discovery workflow, SSE progress | R1 |
| 4 | DISCOVER | "I found 120 relevant papers, including 6 surveys. Want to remove any before we continue?" Can skip | `review_paper_set` checkpoint, beginner view (titles + one-line reason) | R1 |
| 5 | LEARN | **Topic primer** opens at beginner level: what the field is trying to do, why it matters, 3–5 main ideas, each linked to the survey/foundational paper it comes from. Background explanations (e.g. "what is a graph") are visibly labelled | Tutor agent, grounded in surveys; background blocks labelled | R1 |
| 6 | LEARN | **Field map** card: "This topic has 5 main areas" (e.g. molecular property prediction, molecule generation, drug–target interaction…). Each area: a sentence, 2 starter papers, 2 recent papers | Field map workflow | R1 |
| 7 | LEARN | **Your learning path**: 1. Concept: graphs & molecules as graphs → 2. Concept: message passing → 3. Read: survey X (sections 1–3) → 4. Read: foundational paper Y → … Each step says why it's there | Learning Path Planner | R1 |
| 8 | UNDERSTAND | Opens paper Y in **Read with me**. Left: the paper's sections. Right: plain-language explanation of the current section. Technical terms are underlined; hovering shows a glossary definition | GROBID sections + Tutor on demand, cached | R1 |
| 9 | UNDERSTAND | Clicks **Explain more simply** / **Go deeper** on any explanation | Same subject, different level; cached separately | R1 |
| 10 | UNDERSTAND | Clicks an equation → symbol-by-symbol explanation, quoting where the paper defines each symbol; a tiny numerical example | Equation explainer (arXiv LaTeX source) | R2 |
| 11 | UNDERSTAND | **Try it:** a 15-line Python exercise implementing one message-passing step, marked "AI-generated, not run" | Exercises | R2 |
| 12 | PERSIST | Marks papers as read, adds notes; next week the dashboard says "You're on step 5 of 9. Next: read section 4 of survey X" | `reading_status`, learning path progress, Journey Guide | R1 |
| 13 | COMPARE (later) | When ready, the journey bar suggests **Compare** — a simple table of the 5 papers they read: what each does, data used, main result (with quotes) | Comparison agent, beginner column set | R2 |

**What the beginner never sees:** agents, embeddings, query syntax, API
settings, extraction confidence scores. All available under "How was this
found?" if they get curious.

## 12.2 Advanced journey — "Is there a defensible gap here, and can I test it?"

**Persona:** third-year PhD student. **Topic:** "test-time adaptation under
distribution shift for vision models". **Level:** Expert. **Objective:** Find
a research gap.

| # | Stage | What the user does / sees | Underneath | Release |
|---|---|---|---|---|
| 1 | Start | Topic, Expert, Find a research gap; opens Advanced options to set year ≥ 2019, adds two must-include papers by arXiv ID | Config, pinned seeds | R1 |
| 2 | DISCOVER | Edits the query plan directly (adds a query, drops one source) | Planner checkpoint, advanced view (raw queries per source) | R1 |
| 3 | DISCOVER | Reviews the paper set in a dense table: relevance components, roles with reasons, possible duplicates; excludes 30, re-runs expansion once | `review_paper_set`, advanced view | R1 |
| 4 | UNDERSTAND | Field map with citation-community structure, direction relationships, frequent authors, per-direction counts | Field map workflow | R1 |
| 5 | UNDERSTAND | Starts **Analyse full texts** for 80 included papers. Status: 62 retrieved, 18 unavailable (reasons shown); uploads 4 PDFs they have access to | Analysis workflow, PDF upload | R2 |
| 6 | COMPARE | Builds a comparison table: method family × adaptation signal × datasets × reported accuracy under shift × limitations; every cell opens the quote; empty cells say "not reported" | Comparison agent | R2 |
| 7 | COMPARE | **Evolution view** of one direction: lineage of "improves on" relations over time | `paper_relations` + citation lineage | R2 |
| 8 | COMPARE | **Conflicts:** two papers report materially different results on the same dataset/metric/setting; flagged with both quotes and a comparability check (split, backbone) | Conflict detection | R2 |
| 9 | INVESTIGATE | **Gap Detective:** recurring limitations (e.g. "evaluated only on synthetic corruptions" across 9 papers, 6 groups), sparse intersections (heatmap), each with signal numbers | Gap pipeline | R3 |
| 10 | INVESTIGATE | Opens one gap: **Evidence for** (limitation quotes) and **Evidence against** (3 papers found by contradiction/overlap searches that partially address it) | Overlap + contradiction probes | R3 |
| 11 | VALIDATE | Generates hypotheses for open gaps; each shows falsification criteria, novelty check ("no close match in 14 searches across 3 sources on 2026-11-10"), and red-team objections | Novelty + Red-Team | R3 |
| 12 | VALIDATE | Shortlists 2, rejects 1 with a reason (logged) | `hypotheses.user_status`, decisions | R3 |
| 13 | INNOVATE | **Experiment plan:** standard benchmarks and baselines in this corpus (with counts), recommended metrics, reported protocols, suggested ablations (AI-labelled), compute from reported hardware/time where available, linked implementations | Benchmark & Experiment Intelligence | R4 |
| 14 | INNOVATE | Exports a proposal draft (LaTeX + BibTeX) | Report workflow | R4 |
| 15 | PERSIST | Tracks the experiment; two months later gets an **impact alert**: "New paper (arXiv 2701.xxxxx) overlaps with your accepted idea H2" with the overlapping passage | Monitor + impact detection | R5 |

## 12.3 Intermediate variant — master's literature review

Same start as the beginner with "Some background" and "Review the literature".
Differences: the primer is shorter and more technical; the journey bar
recommends Discover → Understand → Compare; the main output is the
literature review report (R4) built from the comparison tables and notes they
created. Glossary tooltips are on, but explanations start at intermediate.

## 12.4 How one project serves both ends

| Concern | Beginner default | Advanced default | Same underlying data |
|---|---|---|---|
| Checkpoints | Plain-language summary, one button | Raw queries, editable per source | `search_queries` |
| Paper list | Title, one-line reason, read status | Full metadata, relevance components, provenance | `project_papers` |
| Field map | 3–6 named areas with starter papers | Communities, relations, counts, authors | `research_directions` |
| Explanations | Expanded, beginner level | Collapsed, advanced level | `explanations` keyed by level |
| Comparison | 4 columns | All attributes, raw values, settings | extractions |
| AI labels | Always visible | Always visible | `claims.kind` |

A beginner who grows into the topic switches the level in the project
settings; nothing is recomputed except explanations they open next.
