# User Experience

**Status:** canonical. It consolidates `docs/plan/06` and `docs/plan/12`.

## 1. UX principles

1. **One input to start.** Topic, experience level and objective. Everything
   else is optional.
2. **Guided, never locked.** The journey bar recommends one next step, and
   every stage stays reachable.
3. **Plain language by default; depth on demand.** Internals appear only
   under "How was this found / ranked?" and in Settings.
4. **Every claim shows its kind.** The badges are Reported, Extracted, AI
   explanation and Hypothesis (unverified), using colour plus text.
5. **Every recommendation explains itself.** The six-question card answers:
   why relevant, use for, strengths, limitations, priority, missing.
6. **The user decides.** One-click override with an optional reason. The
   system's suggestion stays visible next to the user's choice.
7. **Honest gaps.** "Full text not available (publisher blocks downloads).
   Upload the PDF if you have access." — not a spinner, not a guess.

## 2. The journey bar

```
DISCOVER ✓ │ LEARN ● │ UNDERSTAND ○ │ FILTER ● │ COMPARE ◌ │ INVESTIGATE ◌ │ VALIDATE ◌ │ EXPERIMENT ◌ │ PROPOSE ◌
                   ▲ Next step: "Read the primer (5 min), then start your reading path"
✓ done  ● in progress  ○ ready  ◌ not ready yet (hover: what's needed)
```

The next step is chosen from the objective and the project's state. For
example: "Learn the field" puts LEARN before FILTER; "Find a gap" puts FILTER
before LEARN and skips the primer by default.

## 3. Levels in the interface

| Element | Beginner | Intermediate | Advanced |
|---|---|---|---|
| Checkpoints | One-paragraph summary, one button | Summary + editable list | Raw queries, per-source settings |
| Paper list | Title, tier, one-line "why", read status | + venue/year, role tags | + dimension bands, signals, identifiers |
| Recommendation card | 2–3 statements per question, glossary links | Full card | Full card + signal values, sub-question coverage, neighbours |
| Explanations | Expanded, fundamentals first | Expanded, concise | Collapsed, technical |
| Field map | 3–6 named areas with starter papers | + relations | Communities, counts, authors, signals |
| Comparison | 4 key columns | Main attributes | All attributes, settings, raw values |

Level can be changed per project (Settings) or per explanation ("Explain more
simply" / "Go deeper").

## 4. Recommendation card UX

```
┌─────────────────────────────────────────────────────────────────┐
│ Paper title (2021) · venue                      [Essential ▾]   │
│ Foundational · Method source · Learning resource                │
├─────────────────────────────────────────────────────────────────┤
│ Why it matters for your question                                │
│   • … (Extracted) • … (AI explanation, quotes abstract ↗)       │
│ What you can use it for   → Read in LEARN step 3 · Baseline     │
│ Strengths                 • … (Reported p.6 ↗)                  │
│ Limitations               • … (Reported §5 ↗) • … (Extracted)   │
│ Worth prioritising?       Yes — …                               │
│ Missing information       Full text unavailable → Upload PDF    │
├─────────────────────────────────────────────────────────────────┤
│ 👍 👎 · Report a problem · How was this ranked? · Add note       │
└─────────────────────────────────────────────────────────────────┘
```

- The tier dropdown is the override control. Choosing a different tier asks
  for an optional quick reason.
- "Report a problem" on any statement hides it pending re-verification.
- "How was this ranked?" shows dimension bands, signals with values and
  sources, weights, prompt and model versions.

## 5. User journeys

### 5.1 Beginner — "I don't know where to start"

Second-year undergraduate, topic "graph neural networks for drug discovery",
**New to it**, **Learn the field**.

| # | Stage | Experience | Rel. |
|---|---|---|---|
| 1 | Start | Enters topic, level, objective | R1 |
| 2 | DISCOVER | "I understood your question as: *How are graph neural networks used to predict molecular properties and design drugs?* I'll look for surveys, classic papers and recent work. OK?" → **Looks good** | R1 |
| 3 | DISCOVER | Plain progress: "Searching 3 sources… 214 found, 61 after removing duplicates… following references…" | R1 |
| 4 | FILTER (light) | "**Read first** (6)", "Core for your question (18)", "Later (40)". Each card explains why in two sentences. Can move items between groups | R1 |
| 5 | LEARN | Topic primer at beginner level; background parts labelled; main ideas linked to the surveys they come from | R1 |
| 6 | LEARN | Field map: five named areas, each with two starter and two recent papers and a one-line description | R1 |
| 7 | LEARN | Learning path: concepts and papers in order, each with "why this now"; progress saved | R1 |
| 8 | UNDERSTAND | "Read with me": paper sections on the left, explanation on the right; terms underlined with glossary tooltips; "Explain more simply" / "Go deeper" | R1 |
| 9 | UNDERSTAND | Clicks an equation → symbol-by-symbol explanation quoting the paper's definitions; tiny worked example | R2 |
| 10 | UNDERSTAND | "Try it" exercise (labelled "AI-generated, not run") | R2 |
| 11 | COMPARE | Simple four-column table of the papers they read | R2 |
| 12 | Return visit | "You're on step 5 of 9. Next: read section 4 of survey X." | R1 |

### 5.2 Experienced researcher — "Is there a defensible gap, and can I test it?"

PhD student, topic "test-time adaptation for vision models under natural
distribution shift", **Expert**, **Find a research gap**.

| # | Stage | Experience | Rel. |
|---|---|---|---|
| 1 | Start | Topic, Expert, Find a gap; Advanced options: year ≥ 2019, two pinned arXiv IDs, constraint "single GPU" | R1 |
| 2 | DISCOVER | Edits objective sub-questions and raw queries; adds an exclusion | R1 |
| 3 | FILTER | Dense triage table: tiers, five dimension bands, role tags; sorts by methodological usefulness; overrides 12 items with reasons; accepts an objective suggestion ("exclude domain adaptation with target labels?") | R1 |
| 4 | UNDERSTAND | Field map with communities and relations; starts full-text analysis for the 80 included papers; sees 62 retrieved and 18 unavailable with reasons; uploads 4 PDFs | R1 map / R2 analysis |
| 5 | COMPARE | Comparison table (method family × adaptation signal × datasets × results × limitations); evolution view; conflict flags with comparability checks | R2 |
| 6 | FILTER (resources) | Dataset and metric cards: usage counts, licences, saturation, known criticisms; marks two benchmarks Essential | R2 |
| 7 | INVESTIGATE | Gap candidates with signals; each with **evidence for** and **evidence against** (overlap and contradiction probes) | R3 |
| 8 | VALIDATE | Ideas with falsification criteria, novelty record ("no close match in 14 searches across 3 sources, 2026-11-10"), red-team objections; shortlists two, rejects one with a reason | R3 |
| 9 | EXPERIMENT | Baselines, datasets, metrics and repos with cards; protocols from papers; suggested ablations (AI-labelled); compute estimate from reported hardware only | R4 |
| 10 | PROPOSE | Proposal draft with validated citations; LaTeX + BibTeX export | R4 |
| 11 | Months later | Impact alert: a new paper overlaps accepted idea H2, with the overlapping passage | R5 |

### 5.3 Intermediate — master's literature review
Starts with **Some background** and **Review the literature**. The journey
recommends DISCOVER → FILTER → UNDERSTAND → COMPARE → PROPOSE (review
report). The primer is short and the glossary tooltips are on.

## 6. Pages

| Page | Route | Rel. |
|---|---|---|
| Home / Dashboard | `/` | R0 |
| New project (3-field start) | `/projects/new` | R1 |
| Project overview + journey | `/projects/:id` | R1 |
| Run progress & checkpoints | `/projects/:id/runs/:runId` | R1 |
| Research objective (view/edit, versions) | `/projects/:id/objective` | R1 |
| Filter / Triage (tiers, cards, overrides) | `/projects/:id/filter` | R1 |
| Learn: primer, glossary, learning path | `/projects/:id/learn` | R1 |
| Field map | `/projects/:id/map` | R1 |
| Paper explorer & Read with me | `/projects/:id/papers`, `/papers/:id/read` | R1 |
| Saved items & notes | `/saved` | R1 |
| Project history & decisions | `/projects/:id/history` | R1 |
| Ad-hoc search | `/search` | R1 |
| Compare (tables, evolution, conflicts) | `/projects/:id/compare` | R2 |
| Datasets, benchmarks, metrics | `/projects/:id/resources` | R2 |
| Gap explorer | `/projects/:id/gaps` | R3 |
| Ideas | `/projects/:id/ideas` | R3 |
| Experiment planner & tracker | `/projects/:id/experiments` | R4 |
| Proposal & review reports | `/projects/:id/proposal` | R4 |
| Alerts & monitors | `/projects/:id/alerts` | R5 |

## 7. Core components

`JourneyBar`, `NextStepCard`, `ObjectiveEditor`, `RunProgress`,
`CheckpointPanel`, `TriageTable`, `RecommendationCard`, `TierControl`
(override), `DimensionBands`, `ClaimBadge`, `EvidenceQuote` (opens the PDF at
the page with the quote highlighted), `HowRankedPanel`, `ExplainPanel` (level
switch, streaming), `GlossaryTooltip`, `LearningPath`, `FieldMap`
(Cytoscape), `ReadWithMe`, `ComparisonTable`, `CoverageNotice`,
`MissingInfoList`, `FeedbackControls`, `ExportMenu`.

## 8. Language and accessibility rules

- **Banned terms on default screens** (checked by an automated test): agent,
  embedding, vector, LangGraph, LLM, token, prompt, API key, signal, Stage A,
  Stage B.
- Badges and tiers use both text and colour; contrast meets WCAG 2.1 AA.
- Keyboard: j/k to move, Enter to open, o to override, s to save, x to
  exclude.
- Long tasks: first progress message within 2 s, then an update at least
  every 10 s.
