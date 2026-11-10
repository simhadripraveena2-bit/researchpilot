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

Two recurring tools sit across the whole journey rather than inside one
stage:

- **Latest Research** — a dedicated page answering "what is new in my area
  this week, what matters for my objective, and what should I read first?"
  (§4.12).
- **Ask & Learn** — a conversational research tutor that can be opened from
  anywhere. It knows the project and the paper or section being viewed, and
  still answers general questions (§4.13).

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
| LRN-6 | All explanations (primer, glossary, sections, equations) are delivered through Ask & Learn (§4.13); a one-click "Explain this" opens a tutor conversation anchored to the item |

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

### 4.12 Latest Research (dedicated page)

A recurring discovery capability for recently released work. It reuses
discovery, deduplication, date verification and the Research Intelligence
Engine. It is built so that scheduled scans and notifications (PER-4, PER-5)
can be added later without redesign.

| ID | Requirement |
|---|---|
| LAT-1 | A dedicated **Latest Research** page per project, in the main navigation |
| LAT-2 | Discover recent papers from the project topic, objective sub-questions (subtopics), focus concepts and field-map directions, using the **current objective version** |
| LAT-3 | Default window: rolling **7 days** ending now. Storage and window calculation in **UTC**; all dates and window bounds **displayed in the user's local time zone** (browser zone, overridable); date-only values are shown as dates and never shifted across zones (D23). Presets: 24 h, 7 d, 14 d, 30 d, and a custom range |
| LAT-4 | Sources: arXiv (date-range and category search); **bioRxiv and medRxiv** for life-science objectives or when the user enables them (D22); Semantic Scholar; OpenAlex (basic access by default; paid capabilities can be enabled by configuration later, D24); Crossref (journal articles, authoritative DOI dates and preprint↔publication relations) |
| LAT-5 | Deduplicate across sources and against the existing project record; a recent paper already in the project is shown once with its existing state |
| LAT-6 | Each entry shows: title, authors, the **first public appearance** with its basis and meaning (e.g. "Posted on bioRxiv Nov 8", or "Submitted to arXiv Nov 8 — announcement date not verified"), source(s), date confidence, abstract, paper URL, open-access full-text availability, relevant subtopic(s), relevance to the objective (tier + reason), main contribution, and method, dataset or benchmark introduced **when verifiable** (otherwise "not stated in the abstract"); preprint labelling per LAT-24 |
| LAT-7 | Each relevant entry has a **Latest brief** answering eight questions (LAT-19) and a recommendation card on demand |
| LAT-8 | Link to related papers already in the project, distinguishing **"cites your saved paper"** (from citation data) and **"similar to your saved paper"** (from text similarity) |
| LAT-9 | Actions: save, dismiss (optional reason), add note, mark "read later", open in Ask & Learn |
| LAT-10 | Filters: date range, release type, subtopic, methodology, source, relevance tier, open-access availability, status (new since last visit, saved, dismissed) |
| LAT-11 | Classify each entry as exactly one release type: **New preprint**, **New publication**, **Published version of an earlier preprint** (separate type, D25), **Revised version of an older paper**, **Older paper newly indexed**, or **Date uncertain**. The default view shows New preprints and New publications. A journal publication of an existing preprint is **never presented as new research**: it appears under Updates, is excluded from "new research" counts and the digest's new-work section, and gets no novelty credit |
| LAT-12 | Never treat a paper as new because its metadata changed. Metadata dates (indexed, deposited, updated, created-in-index) are never used as publication dates |
| LAT-13 | Every date keeps its event type, manifestation, precision, **reporting source**, **upstream provenance** (when the source exposes it) and retrieval timestamp. Confidence distinguishes **verified** (primary, from the system of record), **corroborated** (agreeing claims whose independent provenance is established), **source agreement** (sources agree but independence cannot be established), **single source**, **conflicting** and **uncertain**. Only verified and corroborated dates can place a paper in a release-type tab; all others are **Date uncertain** by default (D28, revised). Independent corroboration is never claimed unless it can be shown. Dates are never invented or rounded |
| LAT-14 | Summary for the window: how many new relevant papers, how many Essential, which overlap with or challenge the project's direction, and a short "What's new this week" digest that cites papers (AI explanation, grounded) |
| LAT-15 | Flag papers that **overlap with** or **challenge** the project's current direction (objective, saved core papers, and from R3 open gaps and accepted ideas), with the passage that shows it |
| LAT-16 | Default ordering by the Latest brief action (Read now → Save for later → Deprioritise), then RIE priority for the objective. Recency is a filter, not a priority signal |
| LAT-17 | Each scan is stored (window, sources, objective version, coverage, failures) so results are reproducible and "new since last visit" works; scans are refreshed on demand and automatically when the page is opened if the last scan is over 24 h old |
| LAT-18 | Source failures and coverage gaps are shown on the page (e.g. "Semantic Scholar unavailable — results may be incomplete") |
| LAT-19 | **Latest brief** for each relevant new paper, answering: (1) what the paper is about; (2) what is new compared with earlier work; (3) what method, dataset or benchmark it introduces; (4) how it relates to the research objective; (5) whether it overlaps with saved papers; (6) whether it challenges existing research assumptions or the user's proposals; (7) whether it suggests a possible research opportunity; (8) whether to **read now, save for later or deprioritise**. Each answer is either evidence-backed or says "Can't tell from the available text" |
| LAT-20 | Recency never implies importance: a new paper's tier and action come from the RIE objective profile only. The date window is a filter |
| LAT-21 | "Possible research opportunity" is shown only when grounded in an author-stated limitation, open problem or future-work statement, or (from R3) a match with an open project gap. It is labelled **Hypothesis (unverified)** |
| LAT-22 | **Preprint ↔ publication matching** is confidence-aware (DOI, arXiv ID, explicit version relations, title and author similarity, publication metadata). Title similarity alone never merges papers. Possible matches are linked, not merged, and the user can confirm or reject them. Original source records and date provenance are preserved after any match (D29) |
| LAT-23 | **Date events are kept separately, never merged into one "date":** preprint submission, first public announcement/posting, revision, journal acceptance (when deposited), journal online publication, final issue publication, and metadata/indexing dates. The work's **first public appearance** is the earliest public-availability event across its manifestations. For arXiv, the v1 submission timestamp and the announcement date (when captured) are both kept; if only the submission date is verified, it is displayed with its meaning. Search-window overlap is never treated as evidence of a release date |
| LAT-24 | **Preprint labelling:** bioRxiv and medRxiv records (and arXiv records) are labelled **"Preprint — not peer-reviewed"** unless the item displayed is a separately matched published manifestation, which is shown as "Journal version (published in …)". Preprint and published manifestations are kept and displayed distinctly; evidence states which version it comes from |

### 4.13 Ask & Learn (interactive research tutor)

The conversational form of the learning assistant. It reuses the Tutor, the
explanation cache, evidence retrieval, the project record and the claim
validator.

| ID | Requirement |
|---|---|
| ASK-1 | Ask about any concept, term, algorithm, equation, architecture, paper, methodology, dataset or research direction |
| ASK-2 | Follow-up questions keep the relevant conversation context: the last 12 turns verbatim plus a structured summary of older turns that carries their evidence references (D26). Conversations are saved per project and can be resumed or deleted |
| ASK-3 | Level per answer: beginner, intermediate or expert (defaults to the project level) |
| ASK-4 | Explanation styles: simple intuitive, step by step, technical, mathematical, practical example, code-oriented, comparison with related concepts |
| ASK-5 | One-click follow-ups: Explain more simply · Give me an example · Explain step by step · Show the mathematics · Compare with… · How would I implement it? · What do I need to know first? |
| ASK-6 | Equations and notation explained step by step. Paper equations come only from extracted equations (arXiv LaTeX source), user selection or verified text, and are never written from memory |
| ASK-7 | Algorithms and architectures explained with examples and pseudocode; code is labelled AI-generated and "not run" |
| ASK-8 | **Context-aware:** knows the project objective, level, glossary and saved items, and what the user is viewing (paper, section, page, selected text, table, card). "What is message passing?" asked while reading a GNN paper is answered in that paper's terms first |
| ASK-9 | **Scope control:** the user can switch between "About this paper", "About my project" and "General" for any question; the active scope is always shown |
| ASK-10 | Paper questions use the paper's extracted content when accessible, and answers link to the supporting sections, pages or verified passages |
| ASK-11 | Content not drawn from the user's papers is labelled **"Background explanation — AI-generated, not from your sources"** |
| ASK-12 | Never fabricate paper claims, equations, quotations or citations. If the paper's available text doesn't answer the question, say so ("Not found in the available text of this paper; this paper is available as abstract only") before giving any background explanation |
| ASK-13 | Identify missing prerequisites and offer a learning sequence, which can be added to the project learning path |
| ASK-14 | Save an answer, or part of one, as a **saved explanation** in the project: an independent copy that keeps its sources and claim kinds and survives conversation deletion; it can also be pinned to an item or noted |
| ASK-15 | Available from paper reading, recommendation cards, literature review, comparison tables, the field map, Latest Research, the glossary and the learning path; selecting text and choosing "Ask" starts a question about that text |
| ASK-16 | Feedback on any answer (helpful, unclear, wrong); "wrong" hides the statement pending review |
| ASK-17 | **Progressive teaching:** "Teach me" (or a concept question) starts a lesson moving through intuition → simple example → technical explanation → mathematical formulation → algorithmic steps → connection to the current paper → practical implementation → short understanding check. Steps that don't apply are skipped with a reason |
| ASK-18 | During a lesson the user can interrupt with a follow-up and resume, ask for a simpler explanation, go deeper, skip directly to advanced material, jump to any step, or stop |
| ASK-19 | **Learning progress is tracked per project**, independently of conversation history: concepts studied, steps seen, level reached, check results, and status (in progress, understood, needs review). It feeds the learning path |
| ASK-20 | **Retention controls:** delete a conversation, delete all conversations, and a project retention policy (keep until deleted, delete after 30/90/365 days, or don't keep history). Deleting conversations never deletes saved explanations or learning progress; resetting progress is a separate, confirmed action |
| ASK-21 | Conversation summaries are AI-generated context, **never evidence**. Evidence references from summarised turns are preserved and re-resolved to the original passages |
| ASK-22 | Unrelated, non-research requests get a short, polite redirect (D27) |
| ASK-23 | **MVP paper-understanding boundaries:** the tutor supports general concept questions; abstract-grounded paper questions; full-text questions **only** when that paper's text was retrieved and processed; equation explanations **only** when the equation text is actually available (R1: user selection verified against the document text; R2: arXiv LaTeX source). Otherwise it answers "Not available in the extracted text" and states the paper's access level (abstract only, full text, retrieval failed). It never claims full-paper understanding from an abstract |

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
- **Dates:** every displayed date comes from a stored source record and
  states its event type and meaning (e.g. "submitted to arXiv", "announced
  on arXiv", "published online (Crossref, as deposited by the publisher)").
  Metadata-change dates are never shown as publication dates. Source
  agreement is not presented as independent corroboration. Dates that are
  not verified or corroborated are marked uncertain. Dates are stored and
  computed in UTC and displayed in the user's local time zone.
- **Tutor:** paper-specific statements must be grounded in retrieved,
  verified passages; everything else is labelled background. Equations
  attributed to a paper must come from its extracted text or source.
  Conversation summaries and earlier AI answers are never evidence.
- **Matching:** papers are never merged on title similarity alone; matches
  keep every source record and date claim.

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
| UX-9 | Latest Research is a top-level navigation item with a "new since last visit" count |
| UX-10 | Ask & Learn opens as a side panel from anywhere (and full-page for history). It shows the active context and scope as removable chips |

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
- **Provider independence:** business logic depends only on the LLM gateway
  interface; provider and model are configured per task. The initial model
  configuration is provisional until D1 is approved.
- **Hosted deployment security (release blockers for any networked
  deployment):** authentication; project-level authorization; user data
  isolation; secret and API-key management; rate limiting and abuse
  protection; secure file access; enforced conversation retention and
  deletion (ARCHITECTURE §11). Local development may run without
  authentication, bound to localhost only.
- **Free operation:** the core discovery, filtering (Stage A), field map and
  persistence features work without any paid API or LLM key, at reduced
  depth.
- **Security and privacy:** keys only in environment variables; secrets
  never logged; only queries, public paper content and the user's objective
  are sent to external services.
- **Accessibility:** WCAG 2.1 AA target.

## 8. Non-goals

- A general-purpose chatbot. Ask & Learn is scoped to research and technical
  learning: general research questions are welcome; unrelated requests get
  a short, polite redirect. *(Changed from the earlier "no open chat" rule
  because of ASK-1 and ASK-9.)*
- Scraping Google Scholar or bypassing paywalls.
- Guaranteed novelty claims.
- Executing generated code before a sandbox exists.
- Multi-tenant SaaS features (billing, organisations) before R5. Hosted
  single- or multi-user deployment is allowed only after the security gate
  (NFR above) passes.
