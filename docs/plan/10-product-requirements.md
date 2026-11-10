# 10. Product requirements (v2)

**Supersedes:** [01-requirements-analysis.md](01-requirements-analysis.md) for
product scope. The engineering requirements in doc 01 (traceability, no
fabrication, reproducibility, resilience, testability) still apply unchanged.

## 10.1 Positioning

> **From Research Beginner to Research Creator.**

ResearchPilot is a persistent research companion that follows one person (or
one project) through the whole research journey:

```
DISCOVER → LEARN → UNDERSTAND → COMPARE → INVESTIGATE → VALIDATE → INNOVATE
```

The differentiator is not any single feature. It is that every stage reads
from and writes to **one connected, evidence-linked research record** for the
project, so:

- what a beginner learns is built from the same papers the expert analysis uses;
- every explanation, comparison, gap and idea can be traced back to sources;
- the project remembers what was read, decided, accepted and rejected, and
  notices when new papers change earlier conclusions.

## 10.2 Target users

| Persona | Typical goal | What they need most | Default level |
|---|---|---|---|
| **New to research** (first project, e.g. 2nd-year undergrad) | "What is this field, and where do I start?" | Plain-language orientation, a reading order, glossary, help reading one paper | Beginner |
| **Undergrad / master's student** | Literature review for a thesis; pick a project | Field map, structured comparison, help with methods and maths, saved collection | Intermediate |
| **PhD student** | Deep review of a subfield; find a defensible gap; plan experiments | Full-text extraction, comparison tables, gap detective, benchmarks, monitoring | Advanced |
| **Experienced researcher** | Stay current; test an idea's novelty; scope a proposal | Fast discovery, novelty and contradiction checks, evidence tables, exports | Advanced |
| **Independent researcher** | Same as PhD, without institutional access | Open-access-first retrieval, clear "full text unavailable" handling | Any |

Users choose a level, but can switch per explanation at any time. The level
changes **how things are explained and what is shown by default**, never which
evidence is used.

## 10.3 Project setup inputs

The main screen asks for only three things:

1. **Topic or question** (free text).
2. **Experience with this topic:** New to it · Some background · Expert.
3. **Objective:**
   - *Learn the field* — orientation, reading path, explanations.
   - *Review the literature* — collection, comparison, review report.
   - *Find a research gap* — gaps, hypotheses, novelty checks.
   - *Plan an experiment* — datasets, baselines, metrics, protocols.
   - *Keep up with the field* — monitoring and updates.

Everything else (sources, year range, limits) has sensible defaults and sits
under "Advanced options".

The objective decides which stages the guided workflow suggests first. It
does not lock anything: every stage is reachable from any objective.

## 10.4 Functional requirements by journey stage

Requirement IDs are used in the prioritisation (doc 14) and acceptance
criteria.

### DISCOVER
| ID | Requirement |
|---|---|
| DIS-1 | Search arXiv, Semantic Scholar and OpenAlex from one topic; deduplicate; enrich metadata and abstracts (existing Milestone 1) |
| DIS-2 | One-hop citation/reference/recommendation expansion with budgets |
| DIS-3 | Classify papers as latest / foundational / related / survey, each with a stated reason |
| DIS-4 | Plain-language checkpoints ("Here's what I plan to search — change anything?") instead of technical ones |

### LEARN (Beginner-to-Expert Learning Mode, Research Learning Assistant)
| ID | Requirement |
|---|---|
| LRN-1 | **Topic primer:** explain the topic from fundamentals at the chosen level, grounded in the project's survey and foundational papers |
| LRN-2 | **Glossary:** key terms found in the project's papers, each with a level-appropriate definition and links to where the term appears |
| LRN-3 | **Prerequisite learning path:** ordered concepts and papers to read, with the reason for each step and progress tracking |
| LRN-4 | **Level switch:** any explanation can be regenerated at beginner / intermediate / advanced |
| LRN-5 | **Paper explainer:** explain a paper section by section (full text when legally available; abstract-only otherwise, clearly labelled) |
| LRN-6 | **Equation explainer:** explain an equation symbol by symbol, with the paper's own definitions quoted where present |
| LRN-7 | **Algorithm/architecture explainer:** step-by-step walkthrough with a small worked example |
| LRN-8 | **Practice:** short coding exercises that illustrate a method, labelled as AI-generated, with a verification status |

### UNDERSTAND
| ID | Requirement |
|---|---|
| UND-1 | Extract contributions, methods, datasets, metrics, results, limitations and assumptions with evidence spans (existing Phase 3) |
| UND-2 | Extract experimental protocols (splits, baselines, hyperparameters, hardware, training time) when reported |
| UND-3 | **Field Navigator:** identify subfields; show each with foundational and recent papers, main methods, datasets and frequently appearing authors |
| UND-4 | Interactive taxonomy and a map of relationships between directions |

### COMPARE (Paper-to-Paper Intelligence)
| ID | Requirement |
|---|---|
| CMP-1 | Structured comparison tables (methods, assumptions, datasets, metrics, results, limitations); empty cells say "not reported" |
| CMP-2 | Identify methodological improvements: "B extends A by …", from citation context + extracted methods, with evidence |
| CMP-3 | Trace evolution of a direction over time (citation lineage + dates) |
| CMP-4 | Detect conflicting findings: same task/dataset/metric/setting with materially different reported results, or opposing claims |

### INVESTIGATE (Research Gap Detective)
| ID | Requirement |
|---|---|
| INV-1 | Recurring limitations across independent groups |
| INV-2 | Under-explored intersections from computed signals |
| INV-3 | Targeted searches for overlapping **and contradicting** work for every gap |
| INV-4 | Evidence for and against each gap, shown side by side |

### VALIDATE
| ID | Requirement |
|---|---|
| VAL-1 | Hypotheses generated only from open gaps, each with falsification criteria |
| VAL-2 | Adversarial novelty evaluation (independent searches + red-team review) |
| VAL-3 | Ranking by significance, feasibility and evidence strength, with visible score components |
| VAL-4 | Novelty phrased as "no close match found in these searches on this date" — never as guaranteed |

### INNOVATE (Benchmark and Experiment Intelligence)
| ID | Requirement |
|---|---|
| INN-1 | Relevant datasets and benchmark tasks with usage counts in the project |
| INN-2 | Standard baselines (methods most often compared against) and recommended metrics, with reasons |
| INN-3 | Implementations and repositories (GitHub, Hugging Face) with link confidence |
| INN-4 | Suggested ablations (AI interpretation, tied to the method's components) |
| INN-5 | Compute estimates **only** from reported hardware/time; otherwise "insufficient information" |
| INN-6 | Experiment plan and research proposal with citations; exports |

### PERSIST (Persistent Research Projects — spans all stages)
| ID | Requirement |
|---|---|
| PER-1 | Project paper collections with reading status, notes, tags |
| PER-2 | Decision log: included/excluded papers, accepted/rejected ideas, with reasons |
| PER-3 | Idea tracking: proposed → shortlisted → accepted / rejected / parked |
| PER-4 | Experiment tracking: plan, status, notes, user-reported results (labelled as such) |
| PER-5 | Scheduled monitoring for new papers |
| PER-6 | **Impact alerts:** detect when a new paper overlaps with an open gap, an accepted idea or a running experiment, and show the evidence |

## 10.5 Evidence and reliability requirements (revised claim taxonomy)

Every statement shown to the user belongs to exactly one of four kinds. The
kind is stored, displayed as a labelled badge, and preserved in exports.

| Kind | Meaning | Must have | Badge |
|---|---|---|---|
| `reported_finding` | What a paper's authors state or report (results, claims) | Paper + verified quote; page/section where available | **Reported** |
| `extracted_observation` | What ResearchPilot extracted or computed across papers (counts, tables, clusters, conflicts) | The data it was computed from (paper IDs, extraction IDs) | **Extracted** |
| `ai_interpretation` | AI explanations, summaries, comparisons in prose, ablation suggestions | Grounding level (below) | **AI explanation** |
| `unverified_hypothesis` | Research ideas and gap hypotheses | Link to the gap, supporting and contradicting evidence, novelty-check record | **Hypothesis (unverified)** |

Grounding levels for `ai_interpretation`:

- `grounded` — explains specific source material (a paper section, an
  equation, a set of papers). Statements about those sources must cite them;
  quotes are verified.
- `background` — general textbook knowledge (e.g. "what a gradient is"). No
  paper source exists in the project, so it is labelled **"Background
  explanation — AI-generated, not from your sources"**. Background
  explanations must not contain claims about specific papers, results or
  numbers; a validator rejects citations, numbers with units, or paper names in
  background text unless they resolve to project papers.

This is the honest answer to "explain from fundamentals": basic concepts often
have no source in the project, so they are labelled instead of being given
invented citations.

Unchanged from v1: never fabricate citations, results, benchmark scores or
novelty claims; citations come only from stored paper records; quotes are
mechanically verified; preserve DOI / arXiv ID / URL / page / section.

## 10.6 User experience requirements

| ID | Requirement |
|---|---|
| UX-1 | One topic input + level + objective starts a project |
| UX-2 | A guided journey bar shows the seven stages, which are ready, which are in progress, and a single recommended next step |
| UX-3 | Long tasks show plain-language progress ("Searching 3 sources… found 214 papers, 61 after removing duplicates") and an estimate when possible |
| UX-4 | Default screens never mention agents, embeddings, vector databases, LangGraph, models or API keys. These appear only under "How was this found?" and in Settings |
| UX-5 | "How was this found?" on any result shows the searches, sources, evidence and method used |
| UX-6 | Beginner defaults: fewer columns, explanations expanded, glossary tooltips on technical terms. Advanced defaults: dense tables, raw values, extraction details |
| UX-7 | Every AI-written block has the kind badge and a "Report a problem" control |
| UX-8 | When full text is unavailable, say so in one sentence with the reason, and offer to upload a PDF the user has access to |

## 10.7 Non-goals (unchanged plus additions)

- Not a general chatbot; there is no open chat box in the MVP. Questions are
  asked in the context of a paper, section, term or table.
- Not a replacement for courses or textbooks; background explanations are
  short and point to sources in the project where possible.
- No execution of generated code in the MVP (exercises are marked
  "not run"). Sandboxed execution is a later option.
- No scraping of Google Scholar; no paywall bypass.
- No guaranteed novelty, ever.
