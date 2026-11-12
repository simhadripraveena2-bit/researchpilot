"""Version Matcher: are two works the same work, versions of one, or different? (D29)

Pure function over two ``WorkView`` s. Evidence (ARCHITECTURE §4.8a):

* **Decisive** - a shared DOI or arXiv ID; an explicit version link from an authoritative
  source (Crossref ``has-preprint`` / ``is-preprint-of``, bioRxiv/medRxiv ``published`` or
  ``/pubs``, the arXiv author-supplied ``doi``).
* **Strong** - both identifiers on one Semantic Scholar record, or both as locations of one
  OpenAlex work, or a Crossref ``is-same-as`` / ``is-version-of`` link.
* **Supporting** - title similarity (token-sort ratio), author overlap (surname + first
  initial) and first-author match, plausible date order.
* **Contradicting** - Part I/II (or other part numbers) differing, comment / reply /
  erratum / correction / retraction markers on one side only, thesis vs. article, disjoint
  author lists, a different first author without an identifier link.

Rules (``RULE_VERSION``):

* explicit reply / comment / correction link -> **related, not same**;
* decisive evidence and nothing contradicting -> **auto-match**;
* strong evidence, title >= 0.92, author overlap >= 0.6 with the first author -> **auto-match**;
* the no-identifier auto-match needs abstract similarity >= 0.90 from embeddings, which do not
  exist before M1b: until then such pairs are at most **possible matches**;
* title >= 0.90 and author overlap >= 0.5 (or decisive evidence with a contradiction) ->
  **possible match**: linked, never merged until the user confirms;
* everything else -> **no match**. Title similarity alone never matches anything.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from researchpilot.domain.enums import MatchOutcome, MatchRelation

RULE_VERSION = "d29-v1"

DECISIVE_LINKS = frozenset({"is-preprint-of", "has-preprint"})
STRONG_LINKS = frozenset({"is-same-as", "is-version-of", "has-version", "same-record-listing"})
RELATED_LINKS = {
    "is-reply-to": MatchRelation.COMMENT_OR_REPLY_OF,
    "has-reply": MatchRelation.COMMENT_OR_REPLY_OF,
    "is-comment-on": MatchRelation.COMMENT_OR_REPLY_OF,
    "has-comment": MatchRelation.COMMENT_OR_REPLY_OF,
    "is-correction-of": MatchRelation.ERRATUM_OF,
    "has-correction": MatchRelation.ERRATUM_OF,
    # Crossref update-to / updated-by notices (stored with these link types)
    "is-retraction-of": MatchRelation.ERRATUM_OF,
    "has-retraction": MatchRelation.ERRATUM_OF,
    "is-expression-of-concern-for": MatchRelation.ERRATUM_OF,
    "has-expression-of-concern": MatchRelation.ERRATUM_OF,
}
LINK_STRENGTH = {
    **dict.fromkeys(DECISIVE_LINKS, "decisive"),
    **dict.fromkeys(STRONG_LINKS, "strong"),
    **dict.fromkeys(RELATED_LINKS, "related"),
}

TITLE_AUTO_STRONG = 0.92
AUTHORS_AUTO_STRONG = 0.6
TITLE_POSSIBLE = 0.90
AUTHORS_POSSIBLE = 0.5
MAX_PREPRINT_TO_PUBLICATION_DAYS = 4 * 366


@dataclass(frozen=True)
class Link:
    link_type: str
    target_scheme: str
    target_value: str
    source: str


@dataclass(frozen=True)
class WorkView:
    paper_id: uuid.UUID
    title: str
    authors: tuple[str, ...]
    identifiers: frozenset[tuple[str, str]]
    links: tuple[Link, ...] = ()
    manifestation_kinds: frozenset[str] = frozenset()
    publication_type: str | None = None
    earliest_preprint: date | None = None
    earliest_published: date | None = None


@dataclass(frozen=True)
class MatchResult:
    outcome: MatchOutcome
    relation: MatchRelation
    confidence: float
    features: dict[str, Any] = field(default_factory=dict)

    @property
    def merges(self) -> bool:
        return self.outcome is MatchOutcome.AUTO_MATCH


def evaluate(a: WorkView, b: WorkView) -> MatchResult:
    shared = sorted(a.identifiers & b.identifiers)
    links = _links_between(a, b) + _links_between(b, a)
    decisive = [ln for ln in links if LINK_STRENGTH[ln["type"]] == "decisive"]
    strong = [ln for ln in links if LINK_STRENGTH[ln["type"]] == "strong"]
    related = [ln for ln in links if LINK_STRENGTH[ln["type"]] == "related"]

    title = title_similarity(a.title, b.title)
    keys_a, keys_b = author_keys(a.authors), author_keys(b.authors)
    overlap = _overlap(keys_a, keys_b)
    first_author = bool(keys_a and keys_b and keys_a[0] == keys_b[0])
    has_identifier_link = bool(shared or decisive or strong)
    contradicting = _contradictions(
        a, b, keys_a, keys_b, overlap, first_author, has_identifier_link
    )
    features: dict[str, Any] = {
        "doi_match": any(s == "doi" for s, _ in shared),
        "arxiv_match": any(s == "arxiv" for s, _ in shared),
        "shared_identifiers": [f"{s}:{v}" for s, v in shared],
        "explicit_relation": decisive,
        "strong_links": strong,
        "related_links": related,
        "title_sim": round(title, 4),
        "author_overlap": None if overlap is None else round(overlap, 4),
        "first_author_match": first_author,
        "abstract_sim": None,  # needs embeddings (M1b)
        "date_order": _date_order(a, b),
        "contradicting": contradicting,
    }
    relation = _version_relation(a, b)

    if related and not (shared or decisive):
        return MatchResult(
            MatchOutcome.RELATED_NOT_SAME, RELATED_LINKS[related[0]["type"]], 0.9, features
        )
    if (shared or decisive) and not contradicting:
        return MatchResult(MatchOutcome.AUTO_MATCH, relation, 0.99, features)
    if (
        strong
        and not contradicting
        and title >= TITLE_AUTO_STRONG
        and overlap is not None
        and overlap >= AUTHORS_AUTO_STRONG
        and first_author
    ):
        return MatchResult(MatchOutcome.AUTO_MATCH, relation, 0.95, features)
    if shared or decisive:  # identifier evidence but something contradicts it
        return MatchResult(MatchOutcome.POSSIBLE_MATCH, relation, 0.7, features)
    if (
        not contradicting
        and title >= TITLE_POSSIBLE
        and overlap is not None
        and overlap >= AUTHORS_POSSIBLE
    ):
        confidence = round(0.5 + 0.3 * min(title, overlap) + (0.1 if strong else 0.0), 3)
        return MatchResult(MatchOutcome.POSSIBLE_MATCH, relation, min(confidence, 0.89), features)
    return MatchResult(MatchOutcome.NO_MATCH, MatchRelation.UNRELATED, 0.0, features)


def _links_between(source: WorkView, target: WorkView) -> list[dict[str, str]]:
    return [
        {
            "type": ln.link_type,
            "source": ln.source,
            "from": str(source.paper_id),
            "target": f"{ln.target_scheme}:{ln.target_value}",
        }
        for ln in source.links
        if ln.link_type in LINK_STRENGTH
        and (ln.target_scheme, ln.target_value) in target.identifiers
    ]


def _version_relation(a: WorkView, b: WorkView) -> MatchRelation:
    a_pre = a.manifestation_kinds == {"preprint"}
    b_pre = b.manifestation_kinds == {"preprint"}
    if a_pre and "published" in b.manifestation_kinds and not b_pre:
        return MatchRelation.PREPRINT_OF
    if b_pre and "published" in a.manifestation_kinds and not a_pre:
        return MatchRelation.PUBLISHED_VERSION_OF
    return MatchRelation.SAME_WORK


# --- supporting evidence ---------------------------------------------------------------


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^\w\s]", " ", text.replace("$", " ")).split())


def title_similarity(a: str, b: str) -> float:
    """Normalised token-sort ratio in [0, 1]."""
    ta, tb = " ".join(sorted(_normalize(a).split())), " ".join(sorted(_normalize(b).split()))
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def author_key(name: str) -> str | None:
    """Surname + first initial: "Chen, X." / "Xin Chen" / "X. Chen" -> "chen:x"."""
    if "," in name:
        family_part, _, given_part = name.partition(",")
        family_tokens = _normalize(family_part).split()
        given_tokens = _normalize(given_part).split()
    else:
        tokens = _normalize(name).split()
        if not tokens:
            return None
        family_tokens, given_tokens = tokens[-1:], tokens[:-1]
    if not family_tokens:
        return None
    initial = given_tokens[0][0] if given_tokens else ""
    return f"{family_tokens[-1]}:{initial}"


def author_keys(names: tuple[str, ...]) -> list[str]:
    return [k for k in (author_key(n) for n in names) if k]


def _overlap(a: list[str], b: list[str]) -> float | None:
    if not a or not b:
        return None  # cannot be established
    return len(set(a) & set(b)) / min(len(set(a)), len(set(b)))


def _date_order(a: WorkView, b: WorkView) -> str:
    pairs = [
        (a.earliest_preprint, b.earliest_published),
        (b.earliest_preprint, a.earliest_published),
    ]
    for preprint, published in pairs:
        if preprint and published:
            gap = (published - preprint).days
            if gap < -31 or gap > MAX_PREPRINT_TO_PUBLICATION_DAYS:
                return "implausible"
            return "plausible"
    return "unknown"


# --- contradicting evidence --------------------------------------------------------------

_PART = re.compile(r"\bpart\s+(i{1,3}|iv|v|vi{1,3}|ix|x|\d+)\b")
_MARKERS = {
    "comment": re.compile(r"^(a\s+)?comments?\s+on\b|^comment\b"),
    "reply": re.compile(r"^(author\s+)?(reply|response)\s+to\b|^reply\b"),
    "erratum": re.compile(r"^(erratum|corrigendum|correction)\b|\b(erratum|corrigendum)\b"),
    "retraction": re.compile(r"^(retraction|retracted|withdrawn)\b|\bretraction\s+note\b"),
}
_THESIS_TYPES = {"dissertation", "thesis"}


def title_markers(title: str) -> dict[str, str]:
    text = _normalize(title)
    found = {name: "yes" for name, pattern in _MARKERS.items() if pattern.search(text)}
    part = _PART.search(text)
    if part:
        found["part"] = part.group(1)
    return found


def _contradictions(
    a: WorkView,
    b: WorkView,
    keys_a: list[str],
    keys_b: list[str],
    overlap: float | None,
    first_author: bool,
    has_identifier_link: bool,
) -> list[str]:
    out: list[str] = []
    ma, mb = title_markers(a.title), title_markers(b.title)
    if ma.get("part") != mb.get("part"):
        out.append("part_number_differs")
    for marker in ("comment", "reply", "erratum", "retraction"):
        if (marker in ma) != (marker in mb):
            out.append(f"{marker}_marker_one_side")
    ta, tb = (a.publication_type or "").lower(), (b.publication_type or "").lower()
    if (ta in _THESIS_TYPES) != (tb in _THESIS_TYPES) and ta and tb:
        out.append("thesis_vs_article")
    if overlap == 0.0:
        out.append("disjoint_authors")
    elif keys_a and keys_b and not first_author and not has_identifier_link:
        out.append("different_first_author")
    if _date_order(a, b) == "implausible":
        out.append("implausible_date_order")
    return out
