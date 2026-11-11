"""Identifier parsing and normalisation (M1a task 1), with property tests."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from researchpilot.domain.identifiers import (
    Identifier,
    IdentifierScheme,
    InvalidIdentifier,
    arxiv_id_from_doi,
    parse_identifier,
)

S = IdentifierScheme


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # arXiv, new style (4- and 5-digit eras), versions, prefixes and URLs
        ("1706.03762", Identifier(S.ARXIV, "1706.03762")),
        ("arXiv:1706.03762v7", Identifier(S.ARXIV, "1706.03762", 7)),
        ("ARXIV:0704.0001", Identifier(S.ARXIV, "0704.0001")),
        ("https://arxiv.org/abs/2401.01234v2", Identifier(S.ARXIV, "2401.01234", 2)),
        ("arxiv.org/pdf/2401.01234v3.pdf", Identifier(S.ARXIV, "2401.01234", 3)),
        ("http://export.arxiv.org/abs/1501.00001", Identifier(S.ARXIV, "1501.00001")),
        # arXiv, old style; the subject class is not part of the identifier
        ("hep-th/9711200", Identifier(S.ARXIV, "hep-th/9711200")),
        ("math.GT/0309136v2", Identifier(S.ARXIV, "math/0309136", 2)),
        ("arXiv:cond-mat/0207270", Identifier(S.ARXIV, "cond-mat/0207270")),
        ("https://arxiv.org/abs/hep-th/9711200v3", Identifier(S.ARXIV, "hep-th/9711200", 3)),
        # DOIs: case-insensitive, resolver prefixes, URL encoding, trailing punctuation
        ("10.1038/nature14539", Identifier(S.DOI, "10.1038/nature14539")),
        ("doi:10.1038/NATURE14539", Identifier(S.DOI, "10.1038/nature14539")),
        (
            "https://doi.org/10.1101/2020.03.22.002386",
            Identifier(S.DOI, "10.1101/2020.03.22.002386"),
        ),
        ("http://dx.doi.org/10.1000%2Fxyz123", Identifier(S.DOI, "10.1000/xyz123")),
        ("10.1145/3292500.3330701.", Identifier(S.DOI, "10.1145/3292500.3330701")),
        (
            "https://www.nature.com/doi/10.1038/nature14539",
            Identifier(S.DOI, "10.1038/nature14539"),
        ),
        # Semantic Scholar, OpenAlex, PubMed
        (
            "204e3073870fae3d05bcbc2f6a8e263d9b72e776",
            Identifier(S.S2_PAPER, "204e3073870fae3d05bcbc2f6a8e263d9b72e776"),
        ),
        (
            "https://www.semanticscholar.org/paper/Attention-Is-All/204E3073870FAE3D05BCBC2F6A8E263D9B72E776",
            Identifier(S.S2_PAPER, "204e3073870fae3d05bcbc2f6a8e263d9b72e776"),
        ),
        ("CorpusId:13756489", Identifier(S.S2_CORPUS, "13756489")),
        ("W2741809807", Identifier(S.OPENALEX, "W2741809807")),
        ("https://openalex.org/w2741809807", Identifier(S.OPENALEX, "W2741809807")),
        ("https://api.openalex.org/works/W2741809807", Identifier(S.OPENALEX, "W2741809807")),
        ("PMID:32511466", Identifier(S.PMID, "32511466")),
        ("pmc7239048", Identifier(S.PMCID, "PMC7239048")),
    ],
)
def test_parses_and_normalises(text: str, expected: Identifier) -> None:
    assert parse_identifier(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "12345",  # ambiguous: PMID or CorpusId
        "1706.0376",  # too short
        "1501.0001",  # 4 digits in the 5-digit era
        "1401.00001",  # 5 digits in the 4-digit era
        "0703.0001",  # new-style IDs start in April 2007
        "1713.03762",  # month 13
        "arXiv:1706.03762v0",
        "hep-th/9713200",  # month 13
        "doi:11.1000/x",
        "https://example.com/paper/1",
        "not an identifier",
    ],
)
def test_rejects_invalid(text: str) -> None:
    with pytest.raises(InvalidIdentifier):
        parse_identifier(text)


def test_arxiv_datacite_doi_maps_to_the_arxiv_id() -> None:
    assert arxiv_id_from_doi("10.48550/arXiv.1706.03762") == "1706.03762"
    assert arxiv_id_from_doi("https://doi.org/10.48550/ARXIV.HEP-TH/9711200") == "hep-th/9711200"
    assert arxiv_id_from_doi("10.1038/nature14539") is None


# --- property tests ---------------------------------------------------------------------

new_style = st.builds(
    lambda year, month, seq, version: (
        f"{year:02d}{month:02d}.{seq:0{5 if year >= 15 else 4}d}",
        version,
    ),
    st.integers(7, 40),
    st.integers(1, 12),
    st.integers(1, 9999),
    st.one_of(st.none(), st.integers(1, 30)),
).filter(lambda t: t[0] >= "0704")

old_style = st.builds(
    lambda archive, sc, year, month, num, version: (
        f"{archive}{sc}/{year:02d}{month:02d}{num:03d}",
        f"{archive}/{year:02d}{month:02d}{num:03d}",
        version,
    ),
    st.sampled_from(["hep-th", "math", "cond-mat", "astro-ph", "quant-ph", "cs"]),
    st.sampled_from(["", ".GT", ".AG", ".LG"]),
    st.integers(91, 99) | st.integers(0, 7),
    st.integers(1, 12),
    st.integers(0, 999),
    st.one_of(st.none(), st.integers(1, 30)),
)


@given(new_style, st.sampled_from(["{}", "arXiv:{}", "https://arxiv.org/abs/{}", " {} "]))
def test_new_style_arxiv_forms_agree(case: tuple[str, int | None], template: str) -> None:
    arxiv_id, version = case
    text = arxiv_id + (f"v{version}" if version else "")
    parsed = parse_identifier(template.format(text))
    assert parsed == Identifier(S.ARXIV, arxiv_id, version)
    assert parse_identifier(str(parsed).split(":", 1)[1]) == parsed  # round trip


@given(old_style)
def test_old_style_arxiv_drops_subject_class(case: tuple[str, str, int | None]) -> None:
    written, canonical, version = case
    text = written + (f"v{version}" if version else "")
    assert parse_identifier(f"arXiv:{text}") == Identifier(S.ARXIV, canonical, version)


doi_suffix = st.text(
    # DOI case-insensitivity is defined for ASCII characters (DOI Handbook 2.4).
    alphabet=st.sampled_from(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/()"
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: s[-1] not in ".,;:)]}>\"'" and s.strip() == s)


@given(
    st.integers(1000, 999999999),
    doi_suffix,
    st.sampled_from(["{}", "doi:{}", "https://doi.org/{}", "http://dx.doi.org/{}"]),
)
def test_doi_forms_agree_and_are_case_insensitive(prefix: int, suffix: str, template: str) -> None:
    doi = f"10.{prefix}/{suffix}"
    parsed = parse_identifier(template.format(doi))
    assert parsed.scheme is S.DOI
    assert parsed.value == doi.lower()
    assert parse_identifier(template.format(doi.upper())) == parsed
    assert parse_identifier(parsed.value) == parsed  # idempotent


@given(st.text(max_size=40))
def test_never_crashes_on_arbitrary_text(text: str) -> None:
    try:
        parsed = parse_identifier(text)
    except InvalidIdentifier:
        return
    assert parse_identifier(f"{_PREFIX[parsed.scheme]}:{parsed.value}") == parsed


_PREFIX = {
    S.DOI: "doi",
    S.ARXIV: "arXiv",
    S.S2_PAPER: "s2",
    S.S2_CORPUS: "CorpusId",
    S.OPENALEX: "openalex",
    S.PMID: "PMID",
    S.PMCID: "PMCID",
}
