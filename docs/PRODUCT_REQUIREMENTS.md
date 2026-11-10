# Product Requirements

**Status:** canonical. It consolidates and supersedes
`docs/plan/01-requirements-analysis.md` and
`docs/plan/10-product-requirements.md`, which are kept as history.

## 1. Vision and positioning

> **From Research Beginner to Research Creator.**

ResearchPilot is a persistent, evidence-driven research companion. It follows
a project through the whole research journey:

```
DISCOVER → LEARN → UNDERSTAND → FILTER → COMPARE → INVESTIGATE → VALIDATE → EXPERIMENT → PROPOSE
```

Three things set it apart:

1. **One connected project record.** Every stage reads and writes the same
   evidence-linked record of papers, extractions, assessments, ideas and
   decisions.
2. **Objective-aware judgement.** The Research Intelligence Engine tells the
   user what is useful *for their objective*, why, what for, its strengths and
   limitations, whether to prioritise it, and what is missing.
3. **Level-aware explanation.** Concepts, papers, equations and methods are
   explained for beginners, intermediate users or experts, from the same
   evidence.

## 2. Users

| Persona | Typical goal | Needs most | Default level |
|---|---|---|---|
| New to research | Understand an unfamiliar field and where to start | Orientation, reading order, glossary, help reading papers, clear "read this first" | Beginner |
| Undergraduate / master's | Thesis literature review; choose a project | Field map, filtering with reasons, comparisons, maths and method explanations | Intermediate |
| PhD student | Deep review; defensible gap; experiment plan | Full-text extraction, comparison tables, gap detection, novelty checks, baselines and datasets | Advanced |
| Experienced academic | Stay current; test idea novelty; scope proposals | Fast triage, evidence tables, contradiction checks, monitoring, exports | Advanced |
| Independent researcher | As PhD, without institutional access | Open-access-first retrieval, honest "unavailable" handling, free-source operation | Any |

The level changes **how** things are explained and **what is shown by
default**. It never changes which evidence is used.

## 3. Project setup

The start screen asks for:

1. **Topic or question** (free text).
2. **Experience with this topic:** New to it · Some background · Expert.
3. **Objective:** Learn the field · Review the literature · Find a research
   gap · Plan an experiment · Write a proposal · Keep up with the field.

All other options (sources, years, limits, constraints such as compute
budget or open-data-only) have defaults under "Advanced options". The Planner
turns the inputs into a structured **research objective** (core question,
sub-questions, target tasks, focus concepts, exclusions, constraints). The
user sees it in plain language and can edit it. See
[RESEARCH_INTELLIGENCE_ENGINE §2.1](RESEARCH_INTELLIGENCE_ENGINE.md).

## 4. Functional requirements

IDs are referenced by the roadmap and the evaluation framework. Release
numbers are given in [IMPLEMENTATION_ROADMAP](IMPLEMENTATION_ROADMAP.md).

### 4.1 Research Intelligence Engine (cross-cutting, critical)
| ID | Requirement |
|---|---|
| RIE-1 | Assess papers, methodologies, datasets, benchmarks, metrics, models, repositories, gaps and ideas against the current research objective |
| RIE-2 | Score five dimensions separately: foundational importance, direct relevance, methodological usefulness, experimental usefulness, novelty implications |
| RIE-3 | For every recommendation, answer: why relevant, what it can be used for, strengths, limitations, worth prioritising, missing information |
| RIE-4 | Never use publication date or citation count as the sole measure of usefulness (enforced by rules and tests) |
| RIE-5 | Show priority tiers (Essential / Recommended / Optional / Not useful for this objective / Insufficient information) with reasons |
| RIE-6 | Users can override any classification, with an optional reason; overrides persist across recomputes and are logged |
| RIE-7 | Users can give feedback on cards and individual statements; wrong statements are hidden pending re-verification |
| RIE-8 | Feedback may produce *suggested* objective changes and bounded, visible, undoable weight adjustments; there is no silent learning |
| RIE-9 | "How was this ranked?" shows signals, evidence, weights and versions |
| RIE-10 | Assessments update when the objective or evidence changes, and the user is told when a tier changes |

### 4.2 DISCOVER
| ID | Requirement |
|---|---|
| DIS-1 | Search arXiv, Semantic Scholar and OpenAlex (Crossref for DOI validation); deduplicate; enrich metadata and abstracts |
| DIS-2 | Expand one hop along references, citations and recommendations, within budgets |
| DIS-3 | Detect surveys and tutorials |
| DIS-4 | Plain-language checkpoints for the search plan and the paper set; advanced users get raw queries |
| DIS-5 | Add papers manually by DOI, arXiv ID or other identifier (resolved against sources, never from typed metadata alone) |
| DIS-6 | Record every query, source response and failure for reproducibility |

### 4.3 LEARN
| ID | Requirement |
|---|---|
| LRN-1 | Topic primer at the user's level, grounded in the project's surveys and foundational papers |
| LRN-2 | Glossary of terms found in project papers, with level-appropriate definitions and links to where each term appears |
| LRN-3 | Prerequisite learning path (concepts and papers in order, each with a reason) with progress tracking; paper choice driven by RIE (learning-resource role) |
| LRN-4 | Switch any explanation between beginner, intermediate and advanced |
| LRN-5 | Explain concepts from fundamentals; content with no project source is labelled as background |

### 4.4 UNDERSTAND
| ID | Requirement |
|---|---|
| UND-1 | Retrieve legal full text (arXiv, S2/OpenAlex open-access locations, Unpaywall, user upload); give a precise reason when unavailable |
| UND-2 | Explain papers section by section at the user's level |
| UND-3 | Explain mathematical equations symbol by symbol, quoting the paper's own definitions where present |
| UND-4 | Explain architectures and algorithms step by step with small worked examples |
| UND-5 | Extract contributions, methods, datasets, metrics, results, limitations, assumptions, protocols and compute, each with evidence |
| UND-6 | Field Navigator: subfields, taxonomy, relationships between directions, key papers, methods, datasets and frequent authors per subfield |
| UND-7 | Small coding exercises that illustrate methods, labelled AI-generated with a verification status |

### 4.5 FILTER
| ID | Requirement |
|---|---|
| FIL-1 | Triage view of all items by tier and role tags for the current objective, with the six-question card on demand |
| FIL-2 | Inclusion and exclusion criteria derived from the objective, editable; every exclusion has a reason |
| FIL-3 | Bulk accept, reject and override with reasons; decisions logged |
| FIL-4 | Separate views for "Read first" (learning), "Core for your question", "Methods to know", "Experimental resources" |

### 4.6 COMPARE
| ID | Requirement |
|---|---|
| CMP-1 | Structured comparison tables across papers (methods, assumptions, datasets, metrics, results, limitations); unknown cells say "not reported" |
| CMP-2 | Identify methodological improvements (A improves on or extends B) with evidence |
| CMP-3 | Trace how a research direction evolved over time |
| CMP-4 | Detect conflicting findings with comparability checks (split, setting, backbone) |
| CMP-5 | Compare datasets, metrics, models and repositories using RIE cards side by side |

### 4.7 INVESTIGATE
| ID | Requirement |
|---|---|
| INV-1 | Extract limitations and find recurring limitations across independent author groups |
| INV-2 | Detect under-explored intersections from computed signals |
| INV-3 | For every gap, search for overlapping work **and** contradicting work |
| INV-4 | Show evidence for and against each gap side by side |
| INV-5 | Assess gaps with the RIE (significance, evidence strength, relevance to the objective) |

### 4.8 VALIDATE
| ID | Requirement |
|---|---|
| VAL-1 | Generate hypotheses only from open or partially open gaps, with falsification criteria |
| VAL-2 | Adversarial novelty evaluation: independent searches and a separate red-team review |
| VAL-3 | Rank ideas by significance, feasibility and evidence strength with visible components |
| VAL-4 | Novelty phrased as "no close match found in these N searches across these sources on this date"; never "novel" or "guaranteed" |
| VAL-5 | Track idea status (proposed, shortlisted, accepted, rejected, parked) with reasons |

### 4.9 EXPERIMENT
| ID | Requirement |
|---|---|
| EXP-1 | Recommend datasets, benchmark tasks, standard baselines and metrics via RIE cards |
| EXP-2 | Extract and present experimental protocols from papers |
| EXP-3 | Find implementations (GitHub, Hugging Face) with link confidence |
| EXP-4 | Suggest ablations tied to named method components (labelled AI interpretation) |
| EXP-5 | Estimate compute **only** from reported hardware and time; otherwise "insufficient information" |
| EXP-6 | Track experiments and user-reported results, kept separate from paper-reported results |

### 4.10 PROPOSE
| ID | Requirement |
|---|---|
| PRO-1 | Literature review report with verified citations |
| PRO-2 | Research proposal: problem, related work, gap, hypothesis, method, experiments, risks, references |
| PRO-3 | Exports: Markdown, BibTeX, CSV, LaTeX, PDF; claim kinds preserved |
| PRO-4 | Every factual sentence cites project papers; the citation validator blocks unsupported sentences |

### 4.11 PERSIST (all stages)
| ID | Requirement |
|---|---|
| PER-1 | Project collections, reading status, notes and tags |
| PER-2 | Decision log covering papers, overrides, ideas and objective changes |
| PER-3 | Project history: runs, objective versions, report versions |
| PER-4 | Scheduled monitoring for new papers |
| PER-5 | Impact alerts when new work affects an open gap, an accepted idea or a running experiment |

## 5. Evidence and reliability requirements

### 5.1 Four claim kinds

| Kind | Meaning | Required support | Badge |
|---|---|---|---|
| `reported_finding` | What a paper's authors report | Paper + verified quote; page/section where available | **Reported** |
| `extracted_observation` | What ResearchPilot extracted or computed | The rows or signals it came from | **Extracted** |
| `ai_interpretation` | AI explanations, summaries, prose comparisons, suggestions | `grounded` (cites the sources it interprets) or `background` (explicitly unsourced, with no claims about specific papers or results) | **AI explanation** |
| `unverified_hypothesis` | Research ideas and gap hypotheses | Gap link, evidence for and against, novelty-check record | **Hypothesis (unverified)** |

### 5.2 Hard rules
- Citations come only from stored paper records and are never written by a
  model.
- Quotes are mechanically verified against stored text.
- No fabricated citations, results, benchmark scores, licences, star counts or
  novelty claims.
- Preserve DOIs, arXiv IDs, URLs and page/section references where available.
- Clear, specific messages when full text or metadata is unavailable.
- Classifications show their evidence and confidence, and say "insufficient
  information" instead of guessing.

## 6. User experience requirements
| ID | Requirement |
|---|---|
| UX-1 | A project starts from one topic input plus level plus objective |
| UX-2 | A guided journey bar shows the nine stages, their readiness and one recommended next step |
| UX-3 | Long tasks show plain-language progress |
| UX-4 | Default screens contain no internal jargon (agents, embeddings, vector, LangGraph, LLM, tokens, prompts, API keys) |
| UX-5 | "How was this found / ranked?" is available on every result |
| UX-6 | Beginner defaults: fewer columns, explanations expanded, glossary tooltips. Advanced defaults: dense tables, raw values, signal details |
| UX-7 | Every AI-written block has a kind badge and a "Report a problem" control |
| UX-8 | Overrides are one click, with an optional reason |

## 7. Non-functional requirements

- **Traceability:** claim → evidence span → document (page, section) → paper
  → source record.
- **Reproducibility:** run manifests (config, queries, raw responses, prompt
  and model versions, code version); replay from cache.
- **Resilience:** per-source rate limits, retries with backoff, circuit
  breakers; partial results are labelled.
- **Testability:** agents and signals testable in isolation with fakes and
  recorded fixtures.
- **Cost control:** LLM use bounded by top-K and on-demand generation, with
  per-project budgets.
- **Free operation:** the core discovery, filtering (Stage A), field map and
  persistence features work without any paid API or LLM key, at reduced
  depth.
- **Security and privacy:** keys only in environment variables; secrets
  never logged; only queries, public paper content and the user's objective
  are sent to external services.
- **Accessibility:** WCAG 2.1 AA target.

## 8. Non-goals

- A general open-ended chatbot. Questions are asked in the context of an
  item, section, term or table.
- Scraping Google Scholar or bypassing paywalls.
- Guaranteed novelty claims.
- Executing generated code before a sandbox exists.
- Multi-tenant SaaS features (billing, organisations) before R5.
