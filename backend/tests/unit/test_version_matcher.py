"""Version Matcher rules (D29), including property tests for title-only evidence."""

from __future__ import annotations

import uuid
from datetime import date

from hypothesis import given
from hypothesis import strategies as st

from researchpilot.domain.enums import MatchOutcome as O
from researchpilot.domain.enums import MatchRelation as R
from researchpilot.services.matching.version_matcher import (
    Link,
    WorkView,
    author_key,
    evaluate,
    title_markers,
    title_similarity,
)


def work(
    title: str,
    authors: tuple[str, ...] = ("Xin Chen", "Yu Li"),
    *,
    ids: set[tuple[str, str]] | None = None,
    links: tuple[Link, ...] = (),
    kinds: frozenset[str] = frozenset({"published"}),
    ptype: str | None = "journal-article",
    preprint: date | None = None,
    published: date | None = None,
) -> WorkView:
    return WorkView(
        uuid.uuid4(),
        title,
        authors,
        frozenset(ids or set()),
        links,
        kinds,
        ptype,
        preprint,
        published,
    )


PREPRINT = work(
    "Styxl2 regulates de novo sarcomere assembly",
    ("Chen, X.", "Li, Y."),
    ids={("doi", "10.1101/2022.10.22.513336")},
    kinds=frozenset({"preprint"}),
    ptype="posted-content",
    preprint=date(2022, 10, 22),
    links=(Link("is-preprint-of", "doi", "10.7554/elife.87434", "biorxiv_api"),),
)
JOURNAL = work(
    "Styxl2 regulates de novo sarcomere assembly",
    ("Xin Chen", "Yu Li"),
    ids={("doi", "10.7554/elife.87434")},
    published=date(2024, 6, 3),
)


def test_explicit_preprint_link_auto_matches() -> None:
    r = evaluate(PREPRINT, JOURNAL)
    assert (r.outcome, r.relation) == (O.AUTO_MATCH, R.PREPRINT_OF)
    assert r.features["explicit_relation"][0]["source"] == "biorxiv_api"
    assert r.features["date_order"] == "plausible"
    assert evaluate(JOURNAL, PREPRINT).relation is R.PUBLISHED_VERSION_OF


def test_explicit_link_matches_even_when_the_title_changed() -> None:
    """Real medRxiv -> JAMA Pediatrics pair: completely different titles."""
    pre = work(
        "Longitudinal associations between weight indices, cognition, and mental health",
        ("Li, Z. A.", "Ray, M. K."),
        ids={("doi", "10.1101/2023.12.14.23299828")},
        kinds=frozenset({"preprint"}),
        links=(Link("is-preprint-of", "doi", "10.1001/jamapediatrics.2024.1379", "medrxiv_api"),),
    )
    pub = work(
        "Weight Indices, Cognition, and Mental Health From Childhood to Early Adolescence",
        ("Zhaolong Adrian Li", "Mary Katherine Ray"),
        ids={("doi", "10.1001/jamapediatrics.2024.1379")},
    )
    r = evaluate(pre, pub)
    assert r.outcome is O.AUTO_MATCH and r.features["title_sim"] < 0.9


def test_same_title_and_authors_without_identifier_link_is_only_possible() -> None:
    """ResNet arXiv vs CVPR before S2/OpenAlex evidence: identical title and authors."""
    names = ("Kaiming He", "Xiangyu Zhang", "Shaoqing Ren", "Jian Sun")
    arxiv = work(
        "Deep Residual Learning for Image Recognition",
        names,
        ids={("arxiv", "1512.03385")},
        kinds=frozenset({"preprint"}),
    )
    cvpr = work(
        "Deep Residual Learning for Image Recognition",
        names,
        ids={("doi", "10.1109/cvpr.2016.90")},
        ptype="proceedings-article",
    )
    assert evaluate(arxiv, cvpr).outcome is O.POSSIBLE_MATCH


def test_strong_evidence_with_title_and_authors_auto_matches() -> None:
    names = ("Kaiming He", "Xiangyu Zhang", "Shaoqing Ren", "Jian Sun")
    arxiv = work(
        "Deep Residual Learning for Image Recognition",
        names,
        ids={("arxiv", "1512.03385")},
        kinds=frozenset({"preprint"}),
        links=(Link("same-record-listing", "doi", "10.1109/cvpr.2016.90", "semantic_scholar"),),
    )
    cvpr = work(
        "Deep Residual Learning for Image Recognition", names, ids={("doi", "10.1109/cvpr.2016.90")}
    )
    r = evaluate(arxiv, cvpr)
    assert r.outcome is O.AUTO_MATCH and r.confidence == 0.95


def test_part_one_and_part_two_never_match() -> None:
    authors = ("M. Schumacher", "N. Roßner", "W. Vach")
    p1 = work("Neural networks and logistic regression: Part I", authors)
    p2 = work("Neural networks and logistic regression: Part II", authors[::-1])
    r = evaluate(p1, p2)
    assert r.outcome is O.NO_MATCH and "part_number_differs" in r.features["contradicting"]
    assert r.features["title_sim"] > 0.95  # very similar titles, still no match


def test_authorless_record_with_identical_title_never_matches() -> None:
    """Nature Reviews Methods Primers: two different items titled 'Graph neural networks'."""
    primer = work("Graph neural networks", ("Gabriele Corso", "Hannes Stark"))
    summary = work("Graph neural networks", ())
    r = evaluate(primer, summary)
    assert r.outcome is O.NO_MATCH and r.features["author_overlap"] is None


def test_reply_link_is_related_not_same() -> None:
    comment = work(
        "A Review of the Science Around Monarch Butterflies Should Contain a Correction",
        ("Andrew K. Davis",),
        ids={("doi", "10.3390/insects17070712")},
    )
    reply = work(
        "The Preponderance of Evidence Indicates That the Eastern Monarch",
        ("Karen S. Oberhauser",),
        ids={("doi", "10.3390/insects17070713")},
        links=(Link("is-reply-to", "doi", "10.3390/insects17070712", "crossref"),),
    )
    r = evaluate(reply, comment)
    assert (r.outcome, r.relation) == (O.RELATED_NOT_SAME, R.COMMENT_OR_REPLY_OF)


def test_decisive_link_with_contradiction_needs_the_user() -> None:
    erratum = work(
        "Erratum: Styxl2 regulates de novo sarcomere assembly",
        ("Xin Chen",),
        ids={("doi", "10.7554/elife.99999")},
        links=(Link("has-preprint", "doi", "10.1101/2022.10.22.513336", "crossref"),),
    )
    assert evaluate(erratum, PREPRINT).outcome is O.POSSIBLE_MATCH


def test_comment_marker_on_one_side_blocks_a_possible_match() -> None:
    a = work("Quantum supremacy using a programmable superconducting processor", ("F. Arute",))
    b = work(
        "Comment on Quantum supremacy using a programmable superconducting processor", ("F. Arute",)
    )
    assert evaluate(a, b).outcome is O.NO_MATCH


def test_disjoint_authors_and_different_first_author() -> None:
    a = work("Attention is all you need", ("Ashish Vaswani", "Noam Shazeer"))
    b = work("Attention is all you need", ("Jane Doe", "John Roe"))
    assert evaluate(a, b).outcome is O.NO_MATCH
    assert "disjoint_authors" in evaluate(a, b).features["contradicting"]


def test_implausible_date_order_blocks_matching() -> None:
    pre = work("A study", ("X. Chen",), kinds=frozenset({"preprint"}), preprint=date(2015, 1, 1))
    pub = work("A study", ("X. Chen",), published=date(2024, 1, 1))
    assert evaluate(pre, pub).outcome is O.NO_MATCH


def test_author_keys_across_formats() -> None:
    assert author_key("Chen, X.") == author_key("Xin Chen") == author_key("X. Chen") == "chen:x"
    assert author_key("Li, Z. A.") == author_key("Zhaolong Adrian Li") == "li:z"
    assert author_key("De Santis, Andrea") == author_key("Andrea De Santis")
    assert title_markers("Neural networks: Part II")["part"] == "ii"
    assert title_similarity("The large $N$ limit", "The Large-N Limit") == 1.0


# --- properties ---------------------------------------------------------------------------

titles = st.text(alphabet="abcdefghij klmnop", min_size=5, max_size=60)
names = st.lists(
    st.sampled_from(["Ana Silva", "Bo Chen", "Cy Diaz", "Di Evans", "Ed Fox"]), max_size=4
).map(tuple)


@given(titles, names, names)
def test_title_similarity_alone_never_matches(
    title: str, a: tuple[str, ...], b: tuple[str, ...]
) -> None:
    """Identical titles, any authors, no identifier link: never an auto-match (and only a
    possible match when the authors also agree)."""
    r = evaluate(work(title, a), work(title, b))
    assert r.outcome is not O.AUTO_MATCH
    if r.outcome is O.POSSIBLE_MATCH:
        assert r.features["author_overlap"] is not None and r.features["author_overlap"] >= 0.5


@given(titles, titles, names)
def test_result_is_symmetric_in_outcome(t1: str, t2: str, a: tuple[str, ...]) -> None:
    x, y = work(t1, a), work(t2, a)
    assert evaluate(x, y).outcome is evaluate(y, x).outcome
