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
7. **Help is always one click away.** Ask & Learn opens from anywhere and
   already knows what you're looking at.
8. **Honest gaps.** "Full text not available (publisher blocks downloads).
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
| Latest Research | "Read now" list with brief questions 1, 4 and 8; other tabs collapsed | + subtopic, release type, method | + dimension bands, date provenance, source coverage |
| Ask & Learn | Intuitive style first, fundamentals, glossary links | Concise technical | Technical/mathematical first, notation, references to sections |

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

## 4a. Latest Research page

```
┌ Latest Research ───────────────────────── [Last 7 days ▾] [Refresh] ┐
│ Nov 3, 14:00 – Nov 10, 14:00 CET · scanned 2 h ago                    │
│ arXiv ✓ bioRxiv ✓ medRxiv ✓ Semantic Scholar ✓ OpenAlex ✓ (basic)     │
│ Crossref ⚠ partial (rate limited)                                     │
├───────────────────────────────────────────────────────────────────────┤
│ This week: 23 relevant new papers · 4 Read now · 2 overlap with your   │
│ saved papers · 1 challenges a paper you saved      [What's new digest] │
├───────────────────────────────────────────────────────────────────────┤
│ [New research (23)] [Updates (9)] [Newly indexed (5)] [Date uncertain (6)]
│ Filters: action ▾ subtopic ▾ method ▾ source ▾ relevance ▾ OA ▾ new ▾  │
├───────────────────────────────────────────────────────────────────────┤
│ ● NEW PREPRINT · v1 submitted Nov 9, 00:30 CET (arXiv) ⓘ               │
│ Title … · Authors … · Open-access PDF ✓          [▶ Read now ▾] [Essential ▾]
│ Subtopic: SQ2 Natural distribution shift                              │
│ 1 About          … (AI explanation, quotes abstract ↗)                │
│ 2 What's new     "Unlike prior work, we …" (Reported, abstract)       │
│ 3 Introduces     Benchmark: "…" (Reported) · Method: not stated       │
│ 4 Your objective Directly addresses SQ2 (AI explanation ↗)            │
│ 5 Overlap        Cites P12 · similar to P3                            │
│ 6 Challenges     ⚠ Challenges an assumption in P7 (quotes both ↗)     │
│ 7 Opportunity    Authors note "…remains open" → possible opportunity  │
│                  (Hypothesis, unverified)                             │
│ 8 Recommendation Read now — Essential for SQ2 and challenges P7       │
│ [Save] [Read later] [Dismiss ▾] [Note] [Ask about this] [Full card]    │
└───────────────────────────────────────────────────────────────────────┘
```

- **Tabs** map to release types. *New research* = new preprints + new
  publications. *Updates* = revised versions + published versions of earlier
  preprints (e.g. "Journal version of a preprint from March 2026"). *Newly
  indexed* = older papers that only just appeared in a source. *Date
  uncertain* = papers whose date couldn't be confirmed.
- **Beginner view** shows questions 1, 4 and 8 expanded and the rest behind
  "More". **Advanced view** shows all eight plus dimension bands.
- **Action chip** (Read now / Save for later / Deprioritise / Check
  manually) has a dropdown to change it. The change is stored as an
  override. The default sort is by action, then tier, **never by date**.
- **Time zones:** all times are shown in the user's local zone, with the
  abbreviation. Date-only values (e.g. journal publication dates) are shown
  as dates without a time and are never shifted between days. Window bounds
  show local start and end times. The zone can be changed in Settings.
- **ⓘ date provenance** lists every date claim (type, source, manifestation,
  precision, retrieval time in local time), the confidence, why the paper is
  in this tab, and "boundary day" when a date-only value sits on the window
  edge.
- **Date uncertain** entries explain why: "Only OpenAlex reports a date
  (Nov 8) — not confirmed by another source", "Sources disagree: Crossref Nov
  2, OpenAlex Nov 8", or "Month only: November 2026".
- **Possible matches** show "Possibly the published version of *…* —
  [Same paper] [Different papers]", with the evidence (DOI/arXiv links,
  title and author similarity). Nothing is merged until the user confirms,
  unless the auto-match rules apply.
- **medRxiv** entries carry "Preprint — not peer-reviewed".
- The page answers the user's questions: what's new (tabs + digest), what's
  relevant (tiers, actions), what changed (question 2), overlap or challenge
  (questions 5–6), and what to read first (default sort).

## 4b. Ask & Learn

Opens as a right-hand panel from any page (and from text selection →
**Ask**). Full history, saved explanations and learning progress are at
`/projects/:id/ask`.

```
┌ Ask & Learn ──────────────────────────────────────────────┐
│ Context: [Reading: Paper P17 · §3.1 p.4 ✕] [Project ✕]     │
│ Scope: (•) About this paper ( ) My project ( ) General     │
│ Level: [Beginner ▾]                         [Teach me ▸]   │
├────────────────────────────────────────────────────────────┤
│ You: What is message passing?                              │
│ In this paper: … (§3.1, p.4 ↗) [Reported]                  │
│ Intuition: … [AI explanation · Background — not from your  │
│ sources]                                                   │
│ Sources: E1 §3.1 p.4 · E2 Eq. (2) ↗                        │
│ You may need first: graphs, node features → [Build a       │
│ learning sequence]                                         │
│ [Simpler] [Example] [Step by step] [Show the maths]        │
│ [Compare with…] [How to implement] · 💾 Save · 👍 👎       │
├────────────────────────────────────────────────────────────┤
│ Ask a follow-up…                                     [Send]│
└────────────────────────────────────────────────────────────┘
```

**Progressive lesson ("Teach me")**

```
┌ Lesson: Message passing ─────────────── Beginner ▾ ───────┐
│ ① Intuition ✓ ② Example ✓ ③ Technical ● ④ Maths ○          │
│ ⑤ Algorithm ○ ⑥ In this paper ○ ⑦ Implement ○ ⑧ Check ○    │
├────────────────────────────────────────────────────────────┤
│ ③ Technical explanation …                                  │
├────────────────────────────────────────────────────────────┤
│ [Next ▸] [Simpler] [Go deeper] [Skip to ▾] [Ask a question] │
│ [Stop lesson]                                              │
└────────────────────────────────────────────────────────────┘
```

- **Steps can be clicked to jump.** Experts start at step 3 and can skip
  straight to ④ or ⑦. Steps that don't apply show the reason ("No paper in
  view", "No standard mathematical formulation").
- **Ask a question** interrupts the lesson. The answer appears inline, and a
  "Resume lesson at ③" chip returns to the same step.
- **Understanding check (⑧):** one to three short questions, with
  immediate feedback; short answers are marked "AI-graded". Never blocking:
  the user can skip.
- **Learning progress** (Learn page and `/projects/:id/ask`): concepts with
  status (in progress, understood, check passed, needs review), steps seen
  and level reached. It's project-level, so it stays after conversations are
  deleted.
- **Saved explanations** library: saved answers and lesson steps with their
  sources and badges. Independent of conversations.
- **Context chips** show exactly what the tutor is using; removing a chip
  removes that context. **Scope** defaults from where the panel opened.
- **Long conversations:** after 12 turns, older turns are summarised for the
  tutor. The full history stays visible to the user (subject to retention),
  and earlier sources stay clickable.
- **Privacy & retention** (Settings → Ask & Learn, and in the panel menu):
  retention policy (keep until deleted / delete after 30, 90, 365 days /
  don't keep history), **Delete this conversation**, **Delete all
  conversations**, and **Reset learning progress** (separate, confirmed).
  The confirmation dialog states what is kept: "Saved explanations and
  learning progress will be kept."

## 4c. Error and uncertainty states

| Situation | What the user sees |
|---|---|
| A source failed or was rate-limited during a scan | Coverage line with ⚠ and "results may be incomplete"; Retry button |
| No relevant new papers in the window | "No relevant new papers between Nov 3 and Nov 10 (CET)", plus "Try 14 days" and the scan coverage; never an unexplained empty grid |
| Date reported by one secondary source only | *Date uncertain*: "Only OpenAlex reports a date (Nov 8) — not confirmed by another source" (D28) |
| Paper's date known only to the month or year | *Date uncertain*, with the claim shown (e.g. "Crossref: November 2026, month only") |
| Sources disagree on a date | *Date uncertain*: "Sources disagree", with all claims shown |
| Date-only value on the window edge | Normal tab, with "boundary day" in the provenance popover |
| Paper's release type changed after a later scan | Badge "Reclassified: now Published version of an earlier preprint (match confirmed)" |
| Possible preprint/journal match | "Possibly the published version of …" with [Same paper] [Different papers] |
| Method/dataset not stated in the abstract | Question 3: "Not stated in the abstract"; missing information: "Full text needed" |
| No opportunity stated by the authors | Question 7: "None stated in the abstract" (never invented) |
| Tutor can't find the answer in the paper | First line: "Not found in the available text of this paper (abstract only / section not parsed)." Then optional background, labelled |
| Paper equation not available | "This paper's equations aren't available as text. Select the equation in the PDF to ask about it." |
| Lesson step not applicable | Step shown as skipped, with the reason |
| Conversation deleted | "Conversation deleted. Saved explanations and learning progress were kept." |
| Tutor question unrelated to research | Short, polite redirect |
| LLM unavailable or budget reached | Tutor, lessons, briefs and digest show "Explanations are unavailable right now"; Latest Research still shows date-verified entries, release types, tiers from deterministic signals, and links |

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
| 8 | UNDERSTAND | "Read with me": paper sections on the left, Ask & Learn on the right, already explaining the current section; terms underlined with glossary tooltips | R1 |
| 8a | UNDERSTAND | Asks "What is message passing?" → answer in this paper's terms with §3.1 p.4 linked, then a labelled background intuition; clicks **Teach me** → lesson: intuition, example, interrupts with "why neighbours?", resumes, asks **Simpler** on the technical step, skips the maths, sees the step "In this paper", passes the check; Ask & Learn notes "graphs" and "node features" as prerequisites → **Build a learning sequence** adds them to the path | R1 (maths from paper equations: R2) |
| 8b | UNDERSTAND | Saves the lesson's technical step as a saved explanation; the Learn page shows "Message passing — check passed". A month later they delete old conversations; saved explanations and progress remain | R1 |
| 9 | UNDERSTAND | Clicks an equation → symbol-by-symbol explanation quoting the paper's definitions; tiny worked example | R2 |
| 10 | UNDERSTAND | "Try it" exercise (labelled "AI-generated, not run") | R2 |
| 11 | COMPARE | Simple four-column table of the papers they read | R2 |
| 12 | Return visit | "You're on step 5 of 9. Next: read section 4 of survey X." | R1 |
| 13 | Latest Research | Sees "3 new papers this week · 1 Read now"; the brief explains in plain words what it's about, why it matters for their question and what is new compared with the survey they read; dates show in their local time; clicks **Ask about this** → "Explain this paper simply" | R1 |

### 5.2 Experienced researcher — "Is there a defensible gap, and can I test it?"

PhD student, topic "test-time adaptation for vision models under natural
distribution shift", **Expert**, **Find a research gap**.

| # | Stage | Experience | Rel. |
|---|---|---|---|
| 1 | Start | Topic, Expert, Find a gap; Advanced options: year ≥ 2019, two pinned arXiv IDs, constraint "single GPU" | R1 |
| 2 | DISCOVER | Edits objective sub-questions and raw queries; adds an exclusion | R1 |
| 2a | Latest Research | Every Monday opens Latest Research (7 days): 23 new relevant papers; filters subtopic SQ2; one Essential preprint is marked **Read now** because it challenges an assumption in P7 (both passages quoted); one entry sits under *Updates* as a v3 revision of an older baseline, not as new work; a journal article appears as "Published version of an earlier preprint" with the 2025 preprint date; one paper dated only by OpenAlex sits in *Date uncertain*; confirms one possible match; saves two, dismisses five ("wrong topic") | R1 |
| 3 | FILTER | Dense triage table: tiers, five dimension bands, role tags; sorts by methodological usefulness; overrides 12 items with reasons; accepts an objective suggestion ("exclude domain adaptation with target labels?") | R1 |
| 4 | UNDERSTAND | Field map with communities and relations; starts full-text analysis for the 80 included papers; sees 62 retrieved and 18 unavailable with reasons; uploads 4 PDFs | R1 map / R2 analysis |
| 4a | UNDERSTAND | In Ask & Learn, technical style: "How does the entropy objective in §3 differ from the one in P7?" → answer grounded in both papers' sections, with equations from LaTeX source (R2); a code-oriented follow-up gives pseudocode labelled "not run" | R1 / R2 |
| 5 | COMPARE | Comparison table (method family × adaptation signal × datasets × results × limitations); evolution view; conflict flags with comparability checks | R2 |
| 6 | FILTER (resources) | Dataset and metric cards: usage counts, licences, saturation, known criticisms; marks two benchmarks Essential | R2 |
| 7 | INVESTIGATE | Gap candidates with signals; each with **evidence for** and **evidence against** (overlap and contradiction probes) | R3 |
| 8 | VALIDATE | Ideas with falsification criteria, novelty record ("no close match in 14 searches across 3 sources, 2026-11-10"), red-team objections; shortlists two, rejects one with a reason | R3 |
| 9 | EXPERIMENT | Baselines, datasets, metrics and repos with cards; protocols from papers; suggested ablations (AI-labelled); compute estimate from reported hardware only | R4 |
| 10 | PROPOSE | Proposal draft with validated citations; LaTeX + BibTeX export | R4 |
| 10a | Monitoring | Turns on weekly scheduled scans for Latest Research | R5 |
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
| **Latest Research** | `/projects/:id/latest` | R1 |
| **Ask & Learn** (history, saved explanations, learning progress; panel available everywhere) | `/projects/:id/ask` | R1 |
| Settings: time zone, default level, Ask & Learn retention | `/settings` | R1 |
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
`MissingInfoList`, `FeedbackControls`, `ExportMenu`, `LatestHeader` (window
picker, coverage), `ReleaseTypeTabs`, `ReleaseBadge` + `DateProvenancePopover`,
`LatestEntryCard`, `RelatedInProject`, `DigestPanel`, `AskPanel`,
`ContextChips`, `ScopeSwitch`, `FollowUpChips`, `StyleMenu`, `AnswerBlock`,
`SourcesList`, `PrerequisiteOffer`, `SaveToProject`, `LatestBrief` (eight questions), `ActionChip`, `PossibleMatchPrompt`, `LocalTime` (time-zone-aware timestamp/date renderer), `LessonStepper`, `LessonControls`, `UnderstandingCheck`, `ResumeLessonChip`, `LearningProgressList`, `SavedExplanationsLibrary`, `RetentionSettings`, `DeleteConversationDialog`.

## 7a. Navigation

```
Home · Projects ▸ [Overview · Latest Research (•3) · Filter · Learn · Map · Papers ·
                   Compare · Gaps · Ideas · Experiments · Proposal · History]
Global: Search · Ask & Learn (panel, shortcut "?") · Saved · Settings
```

Latest Research is project-level navigation, not a journey stage. It feeds
DISCOVER and, through overlap/challenge flags, VALIDATE. Ask & Learn sits
across LEARN and UNDERSTAND and is reachable from every stage.

## 8. Language and accessibility rules

- **Banned terms on default screens** (checked by an automated test): agent,
  embedding, vector, LangGraph, LLM, token, prompt, API key, signal, Stage A,
  Stage B.
- Badges and tiers use both text and colour; contrast meets WCAG 2.1 AA.
- Keyboard: j/k to move, Enter to open, o to override, s to save, x to
  exclude, ? to open Ask & Learn, l to mark read later.
- Long tasks: first progress message within 2 s, then an update at least
  every 10 s.
