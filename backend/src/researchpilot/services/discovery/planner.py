"""Deterministic discovery Planner (rule-based; no language model).

``plan(objective)`` turns one objective version into a ``DiscoveryPlan``: queries with their
terms, the sources each is sent to (rendered in each source's syntax), which sub-questions
each query serves, the exclusions and what the plan does *not* use. The same objective version
and options always give the same plan (``plan_id`` is a hash of its content), so a run can be
re-planned after a crash and get exactly the plan it started with.

Rules:

* **Core query** from the main question (question words and filler removed).
* **One query per sub-question**, anchored on the objective's main topic (first task,
  keyword or concept) so a short sub-question ("Which benchmarks are used?") stays on topic.
* **Expansion queries** (origin ``rule_expansion``), in order, while the query budget lasts:
  synonyms of keywords, tasks and problem areas, focus concepts, preferred or required
  methods, required or preferred datasets and benchmarks.
* **Exclusions** (out-of-scope topics) are hard filters: arXiv queries carry ``ANDNOT``, and
  hits from every source whose title or abstract contains one are recorded as excluded.
  Avoided methods and excluded datasets/benchmarks are softer: hits are flagged, not dropped.
* **Sources:** arXiv, Crossref, Semantic Scholar and OpenAlex search by topic. arXiv is left
  out for domains it does not cover. bioRxiv and medRxiv have no topic search (date intervals
  only): their preprints are reached through DOIs found by the other sources.
* Compute, time and resource constraints do not narrow a literature search; they are kept
  for assessment (M1b) and listed as not applied.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, Field

from researchpilot.domain.enums import SearchOrigin, SourceName
from researchpilot.services.objectives.model import ObjectiveContent

PLANNER_VERSION = "rules-1"
SEARCHABLE = (
    SourceName.ARXIV_API,
    SourceName.CROSSREF,
    SourceName.SEMANTIC_SCHOLAR,
    SourceName.OPENALEX,
)
MAX_TERMS_PER_QUERY = 4  # AND-groups; more makes arXiv's AND search too narrow

# Words that carry no topic in a research question.
_FILLER = frozenset(
    """
    a about across against all also among an and any are as at be been best better between
    both but by can could current currently do does doing done each effect effects either
    for from has have how i if in into is it its kind kinds main make many may might more most
    much my new not of on or other our over should so some such than that the their them
    these they this those through to under up us use used uses using very was we well were
    what when where whether which while who whom whose why will with within without would
    work works working compare compared comparing versus vs approach approaches state art
    existing recent known exist exists help helps improve improves performance best work
    """.split()
)
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9+\-./]*")

# Domains arXiv does not cover (words in the objective's domain or subdomains).
_NOT_ON_ARXIV = frozenset(
    {
        "clinical",
        "medicine",
        "medical",
        "nursing",
        "law",
        "legal",
        "history",
        "education",
        "pharmacy",
        "dentistry",
        "veterinary",
        "humanities",
        "literature",
    }
)
_LIFE_SCIENCE = frozenset(
    {
        "biology",
        "bioinformatics",
        "genomics",
        "neuroscience",
        "medicine",
        "medical",
        "clinical",
        "epidemiology",
        "immunology",
        "microbiology",
        "biochemistry",
        "pharmacology",
        "ecology",
        "health",
    }
)

Purpose = Literal["core", "sub_question", "synonym", "task", "concept", "method", "dataset"]


class PlannedQuery(BaseModel):
    id: str  # Q1, Q2, ... (stable within a plan)
    purpose: Purpose
    origin: SearchOrigin
    text: str  # plain words, as shown to the user
    terms: list[list[str]]  # AND of OR-groups
    sub_question_keys: list[str] = []
    sources: list[SourceName]
    rendered: dict[str, str]  # source -> query in that source's syntax
    rationale: str


class SourceChoice(BaseModel):
    source: SourceName
    used: bool
    reason: str


class DiscoveryPlan(BaseModel):
    plan_id: str  # hash of the content: same objective version + options -> same plan
    planner_version: str = PLANNER_VERSION
    objective_id: uuid.UUID
    objective_version: int
    queries: list[PlannedQuery]
    sub_question_queries: dict[str, list[str]]  # SQ key -> query ids
    search_terms: list[str]
    synonyms: dict[str, list[str]]
    excluded_terms: list[str]  # hits containing these are excluded
    flagged_terms: list[str]  # hits containing these are kept but flagged
    sources: list[SourceChoice]
    max_results_per_query: int
    max_candidates: int
    not_applied: list[str]  # objective parts that do not shape the search, and why
    notes: list[str] = Field(default_factory=list)

    def query(self, query_id: str) -> PlannedQuery:
        return next(q for q in self.queries if q.id == query_id)


class PlanOptions(BaseModel):
    max_queries: int = Field(default=8, ge=1, le=20)
    max_results_per_query: int = Field(default=10, ge=1, le=50)
    max_candidates: int = Field(default=40, ge=1, le=200)
    sources: list[SourceName] | None = None  # restrict to these (default: all searchable)


# --- text helpers --------------------------------------------------------------------------


def keywords(text: str, limit: int = MAX_TERMS_PER_QUERY) -> list[str]:
    """Topic words of a sentence, in order, without filler or repeats."""
    out: list[str] = []
    seen: set[str] = set()
    for word in _WORD.findall(text):
        key = word.lower().strip(".-/")
        if len(key) < 2 or key in _FILLER or key in seen:
            continue
        seen.add(key)
        out.append(word.strip(".-/"))
        if len(out) == limit:
            break
    return out


def phrase_terms(text: str, vocabulary: Sequence[str], limit: int) -> list[str]:
    """Terms of a sentence: the user's own phrases it contains (longest first) stay whole,
    then the remaining topic words, in order of appearance."""
    found: list[tuple[int, str]] = []
    lowered = " " + re.sub(r"[^\w+\-./]+", " ", text).lower() + " "
    for phrase in sorted({v for v in vocabulary if v.strip()}, key=len, reverse=True):
        at = -1
        for needle in (" " + phrase.lower() + " ", " " + phrase.lower() + "s "):  # plural
            at = lowered.find(needle)
            if at >= 0:
                break
        if at >= 0:
            found.append((at, phrase))
            lowered = lowered.replace(needle, " " + "_" * (len(needle) - 2) + " ")
    rest = keywords(lowered.replace("_", " "), MAX_TERMS_PER_QUERY * 2)
    for word in rest:
        found.append((lowered.find(" " + word.lower() + " "), word))
    ordered = [t for _, t in sorted(found, key=lambda x: (x[0] < 0, x[0]))]
    return list(dict.fromkeys(ordered))[:limit]


def _covered(term: str, words: Iterable[str]) -> bool:
    lowered = {w.lower() for w in words}
    return all(part.lower() in lowered for part in term.split())


def render_plain(terms: Sequence[Sequence[str]]) -> str:
    return " ".join(group[0] for group in terms)


def _arxiv_term(term: str) -> str:
    term = term.replace('"', "")
    return f'all:"{term}"' if " " in term else f"all:{term}"


def render_arxiv(terms: Sequence[Sequence[str]], excluded: Sequence[str]) -> str:
    groups = []
    for group in terms:
        rendered = [_arxiv_term(t) for t in group]
        groups.append(rendered[0] if len(rendered) == 1 else "(" + " OR ".join(rendered) + ")")
    query = " AND ".join(groups)
    for term in excluded:
        query += f" ANDNOT {_arxiv_term(term)}"
    return query


def _words(text: str | None) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or "")}


# --- planning ------------------------------------------------------------------------------


def choose_sources(
    content: ObjectiveContent, allowed: list[SourceName] | None
) -> list[SourceChoice]:
    domain_words = _words(content.domain) | set().union(*(_words(s) for s in content.subdomains))
    choices = []
    for source in SEARCHABLE:
        if allowed is not None and source not in allowed:
            choices.append(
                SourceChoice(source=source, used=False, reason="not selected for this run")
            )
        elif source is SourceName.ARXIV_API and domain_words & _NOT_ON_ARXIV:
            choices.append(
                SourceChoice(
                    source=source,
                    used=False,
                    reason="arXiv does not cover this domain "
                    f"({', '.join(sorted(domain_words & _NOT_ON_ARXIV))})",
                )
            )
        else:
            reasons = {
                SourceName.ARXIV_API: "preprints in computer science, mathematics, physics, "
                "statistics, quantitative biology and finance (system of record)",
                SourceName.CROSSREF: "journal and conference publications (system of record "
                "for DOIs)",
                SourceName.SEMANTIC_SCHOLAR: "broad index; hits are resolved to their DOI or "
                "arXiv record",
                SourceName.OPENALEX: "broad index; hits are resolved to their DOI or arXiv "
                "record; lists cited works",
            }
            choices.append(SourceChoice(source=source, used=True, reason=reasons[source]))
    life = domain_words & _LIFE_SCIENCE
    for server in (SourceName.BIORXIV_API, SourceName.MEDRXIV_API):
        choices.append(
            SourceChoice(
                source=server,
                used=False,
                reason="no topic search (date intervals only); its preprints are fetched when "
                "another source lists their DOI"
                + (" - relevant to this life-science objective" if life else ""),
            )
        )
    return choices


def plan(
    objective_id: uuid.UUID,
    version: int,
    content: ObjectiveContent,
    options: PlanOptions | None = None,
) -> DiscoveryPlan:
    options = options or PlanOptions()
    sources = choose_sources(content, options.sources)
    used = [c.source for c in sources if c.used]
    excluded = list(content.exclusions)
    flagged = [
        *content.constraints.methods.avoided,
        *content.constraints.datasets.excluded,
        *content.constraints.benchmarks.excluded,
    ]
    synonyms = {k: list(v) for k, v in content.synonyms.items()}

    anchor_phrase = next(
        iter([*content.target_tasks, *content.keywords, *content.focus_concepts]), None
    ) or (content.domain or "")
    vocabulary = [
        *content.keywords,
        *content.target_tasks,
        *content.problem_areas,
        *content.focus_concepts,
        *synonyms,
        *(alt for alts in synonyms.values() for alt in alts),
        *content.constraints.methods.preferred,
        *content.constraints.methods.required,
        *content.constraints.datasets.required,
        *content.constraints.datasets.preferred,
        *content.constraints.benchmarks.required,
        *content.constraints.benchmarks.preferred,
    ]

    drafts: list[tuple[Purpose, SearchOrigin, list[list[str]], list[str], str]] = []

    def anchor_for(words: Iterable[str]) -> list[list[str]]:
        joined = " ".join(words).lower()
        if (
            not anchor_phrase
            or anchor_phrase.lower() in joined
            or _covered(anchor_phrase, joined.split())
        ):
            return []
        return [[anchor_phrase, *synonyms.get(anchor_phrase, [])[:2]]]

    def group(term: str) -> list[str]:
        return [term, *synonyms.get(term, [])[:2]]

    # Core question: the user's phrases it names stay whole, then its topic words.
    core_terms = [
        group(t) for t in phrase_terms(content.core_question, vocabulary, MAX_TERMS_PER_QUERY)
    ]
    drafts.append(("core", SearchOrigin.PLANNER, core_terms, [], "the main research question"))
    for sq in content.sub_questions:
        words = phrase_terms(sq.text, vocabulary, MAX_TERMS_PER_QUERY - 1)
        terms = anchor_for(words) + [group(w) for w in words]
        key = sq.key or ""
        drafts.append(
            (
                "sub_question",
                SearchOrigin.PLANNER,
                terms,
                [key] if key else [],
                f"sub-question {key}".strip(),
            )
        )

    def expansion(purpose: Purpose, term: str, why: str) -> None:
        terms = [group(term), *anchor_for(term.split())]
        drafts.append((purpose, SearchOrigin.RULE_EXPANSION, terms, [], why))

    for term, alts in synonyms.items():
        for alt in alts[:2]:
            drafts.append(
                (
                    "synonym",
                    SearchOrigin.RULE_EXPANSION,
                    [[alt], *anchor_for(alt.split())],
                    [],
                    f"synonym of '{term}'",
                )
            )
    for task in [*content.target_tasks, *content.problem_areas]:
        expansion("task", task, "research task or problem area")
    for concept in [*content.focus_concepts, *content.keywords]:
        expansion("concept", concept, "keyword or related concept")
    for method in [*content.constraints.methods.required, *content.constraints.methods.preferred]:
        expansion("method", method, "required or preferred method")
    for data in [
        *content.constraints.datasets.required,
        *content.constraints.datasets.preferred,
        *content.constraints.benchmarks.required,
        *content.constraints.benchmarks.preferred,
    ]:
        expansion("dataset", data, "required or preferred dataset or benchmark")

    # Core and every sub-question always; expansions while the budget lasts; no repeats.
    required = sum(1 for d in drafts if d[0] in ("core", "sub_question"))
    budget = max(options.max_queries, required)
    queries: list[PlannedQuery] = []
    seen: set[str] = set()
    for purpose, origin, terms, sq_keys, why in drafts:
        terms = [g for g in terms if g and g[0]][:MAX_TERMS_PER_QUERY]
        if not terms:
            continue
        text = render_plain(terms)
        key = " ".join(sorted(text.lower().split()))
        if key in seen:
            if sq_keys:  # a sub-question whose query repeats another: map it there
                for q in queries:
                    if " ".join(sorted(q.text.lower().split())) == key:
                        q.sub_question_keys = sorted({*q.sub_question_keys, *sq_keys})
            continue
        if len(queries) >= budget:
            break
        seen.add(key)
        rendered = {
            s.value: (render_arxiv(terms, excluded) if s is SourceName.ARXIV_API else text)
            for s in used
        }
        queries.append(
            PlannedQuery(
                id=f"Q{len(queries) + 1}",
                purpose=purpose,
                origin=origin,
                text=text,
                terms=terms,
                sub_question_keys=sq_keys,
                sources=list(used),
                rendered=rendered,
                rationale=why,
            )
        )

    # Sub-question -> queries: its own query, plus queries whose terms it mentions.
    mapping: dict[str, list[str]] = {}
    for sq in content.sub_questions:
        if not sq.key:
            continue
        sq_words = _words(sq.text)
        mapping[sq.key] = [
            q.id
            for q in queries
            if sq.key in q.sub_question_keys
            or (
                q.purpose != "core"
                and q.origin is SearchOrigin.RULE_EXPANSION
                and _covered(q.terms[0][0], sq_words)
            )
        ]

    terms_used = list(dict.fromkeys(t for q in queries for g in q.terms for t in g))
    not_applied = []
    c = content.constraints
    if c.compute.gpu_hours or c.compute.hardware or c.compute.max_cost:
        not_applied.append(
            "compute and cost limits: kept for assessing papers (not a search filter)"
        )
    if c.time.horizon or c.time.deadline:
        not_applied.append(
            "time horizon and deadline: your project's schedule, not a publication date filter"
        )
    if c.resources or c.licences:
        not_applied.append("resources and licence needs: kept for assessing papers")
    if c.datasets.open_access_only:
        not_applied.append(
            "open-access data only: checked when datasets are extracted (later release)"
        )
    notes = []
    if not used:
        notes.append("no searchable source is selected")

    body = {
        "planner_version": PLANNER_VERSION,
        "objective_id": str(objective_id),
        "objective_version": version,
        "queries": [q.model_dump(mode="json") for q in queries],
        "mapping": mapping,
        "excluded": excluded,
        "flagged": flagged,
        "sources": [c.model_dump(mode="json") for c in sources],
        "options": options.model_dump(mode="json"),
    }
    plan_id = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    return DiscoveryPlan(
        plan_id=plan_id,
        objective_id=objective_id,
        objective_version=version,
        queries=queries,
        sub_question_queries=mapping,
        search_terms=terms_used,
        synonyms=synonyms,
        excluded_terms=excluded,
        flagged_terms=flagged,
        sources=sources,
        max_results_per_query=options.max_results_per_query,
        max_candidates=options.max_candidates,
        not_applied=not_applied,
        notes=notes,
    )


def matches(terms: Sequence[str], *texts: str | None) -> list[str]:
    """The terms that occur (as whole words, case-insensitively) in any of the texts."""
    haystack = " " + " ".join(re.sub(r"[^\w]+", " ", t or "").lower() for t in texts) + " "
    found = []
    for term in terms:
        needle = " " + re.sub(r"[^\w]+", " ", term).lower().strip() + " "
        if needle.strip() and needle in haystack:
            found.append(term)
    return found


def describe(p: DiscoveryPlan) -> str:
    """The plan in plain language (shown at the confirmation step)."""
    used = [c.source.value.replace("_api", "").replace("_", " ") for c in p.sources if c.used]
    lines = [
        f"I will run {len(p.queries)} searches in {', '.join(used) or 'no source'}, "
        f"keeping up to {p.max_results_per_query} results per search and looking at up to "
        f"{p.max_candidates} papers in total.",
        *(f"- {q.text} ({q.rationale})" for q in p.queries),
    ]
    if p.excluded_terms:
        lines.append(f"Papers about {', '.join(p.excluded_terms)} will be left out.")
    if p.flagged_terms:
        lines.append(f"Papers mentioning {', '.join(p.flagged_terms)} will be kept but marked.")
    return "\n".join(lines)
