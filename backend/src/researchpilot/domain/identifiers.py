"""Paper identifier parsing and normalisation (M1a task 1).

Accepts what people paste: bare identifiers, prefixed forms (``doi:``, ``arXiv:``,
``CorpusId:``, ``PMID:``) and landing-page/API URLs. Produces one canonical form per scheme,
so ``paper_identifiers(scheme, value)`` can act as the deduplication guard:

* **DOI** - lower-cased (DOIs are case-insensitive), without resolver prefix, URL-decoded.
* **arXiv** - new style ``YYMM.NNNN[N]`` or old style ``archive/YYMMNNN``; the version is
  split off (``value`` never carries it), and an old-style subject class is dropped
  (``math.GT/0309136`` -> ``math/0309136``), which is how arXiv itself identifies the paper.
* **Semantic Scholar** - 40-hex ``paperId`` (lower case) or numeric ``CorpusId``.
* **OpenAlex** - ``W`` + digits (upper-case ``W``).
* **PubMed** - numeric PMID; ``PMC`` + digits.

Bare numbers are refused unless prefixed: ``12345`` could be a PMID or a CorpusId.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import unquote, urlsplit

from researchpilot.core.errors import ValidationFailed


class IdentifierScheme(StrEnum):
    DOI = "doi"
    ARXIV = "arxiv"
    S2_PAPER = "s2_paper"
    S2_CORPUS = "s2_corpus"
    OPENALEX = "openalex"
    PMID = "pmid"
    PMCID = "pmcid"
    DBLP = "dblp"
    ACL = "acl"


class InvalidIdentifier(ValidationFailed):
    """The text is not a recognised paper identifier."""


@dataclass(frozen=True)
class Identifier:
    scheme: IdentifierScheme
    value: str
    version: int | None = None  # arXiv only

    @property
    def canonical(self) -> str:
        return f"{self.scheme.value}:{self.value}"

    def __str__(self) -> str:
        suffix = f"v{self.version}" if self.version is not None else ""
        return f"{self.canonical}{suffix}"


# arXiv: new style since April 2007 (4-digit sequence until 1412, 5 digits from 1501).
_ARXIV_NEW = re.compile(r"^(?P<yymm>\d{4})\.(?P<seq>\d{4,5})(?:v(?P<v>\d+))?$")
# Old style: archive (letters and hyphens), optional subject class, then YYMMNNN.
_ARXIV_OLD = re.compile(
    r"^(?P<archive>[a-z]+(?:-[a-z]+)*)(?:\.[a-z]{2})?/(?P<num>\d{7})(?:v(?P<v>\d+))?$",
    re.IGNORECASE,
)
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_S2_PAPER = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_OPENALEX = re.compile(r"^w\d+$", re.IGNORECASE)
_PMCID = re.compile(r"^pmc\d+$", re.IGNORECASE)
_DIGITS = re.compile(r"^\d+$")

_PREFIXES: dict[str, IdentifierScheme] = {
    "doi": IdentifierScheme.DOI,
    "arxiv": IdentifierScheme.ARXIV,
    "corpusid": IdentifierScheme.S2_CORPUS,
    "s2": IdentifierScheme.S2_PAPER,
    "openalex": IdentifierScheme.OPENALEX,
    "pmid": IdentifierScheme.PMID,
    "pmcid": IdentifierScheme.PMCID,
}

_TRAILING_PUNCTUATION = ".,;:)]}>\"'"

# The arXiv-assigned DataCite DOI for every arXiv paper: 10.48550/arXiv.<id>.
ARXIV_DOI_PREFIX = "10.48550/arxiv."


def parse_identifier(text: str) -> Identifier:
    """Parse one identifier; raises ``InvalidIdentifier`` with a plain-language message."""
    raw = text.strip().strip("<>").strip()
    if not raw:
        raise InvalidIdentifier("Enter a DOI, arXiv ID, Semantic Scholar or OpenAlex ID")
    if "://" in raw or raw.lower().startswith(("doi.org/", "arxiv.org/", "www.")):
        return _from_url(raw)

    prefix, sep, rest = raw.partition(":")
    if sep and prefix.strip().lower() in _PREFIXES:
        return _parse_scheme(_PREFIXES[prefix.strip().lower()], rest.strip())

    for scheme in (
        IdentifierScheme.DOI,
        IdentifierScheme.ARXIV,
        IdentifierScheme.S2_PAPER,
        IdentifierScheme.OPENALEX,
        IdentifierScheme.PMCID,
    ):
        try:
            return _parse_scheme(scheme, raw)
        except InvalidIdentifier:
            continue
    if _DIGITS.match(raw):
        raise InvalidIdentifier(
            "A number on its own is ambiguous; write PMID:<number> or CorpusId:<number>"
        )
    raise InvalidIdentifier(f"Not a recognised paper identifier: {raw!r}")


def _parse_scheme(scheme: IdentifierScheme, value: str) -> Identifier:
    match scheme:
        case IdentifierScheme.DOI:
            return Identifier(scheme, normalize_doi(value))
        case IdentifierScheme.ARXIV:
            arxiv_id, version = normalize_arxiv(value)
            return Identifier(scheme, arxiv_id, version)
        case IdentifierScheme.S2_PAPER:
            if not _S2_PAPER.match(value):
                raise InvalidIdentifier("A Semantic Scholar paper ID has 40 hex characters")
            return Identifier(scheme, value.lower())
        case IdentifierScheme.S2_CORPUS | IdentifierScheme.PMID:
            if not _DIGITS.match(value):
                raise InvalidIdentifier(f"A {scheme.value} is a number")
            return Identifier(scheme, str(int(value)))
        case IdentifierScheme.OPENALEX:
            if not _OPENALEX.match(value):
                raise InvalidIdentifier("An OpenAlex work ID looks like W2741809807")
            return Identifier(scheme, "W" + value[1:])
        case IdentifierScheme.PMCID:
            if not _PMCID.match(value):
                raise InvalidIdentifier("A PMCID looks like PMC1234567")
            return Identifier(scheme, "PMC" + value[3:])
        case _:
            raise InvalidIdentifier(f"Parsing {scheme.value} identifiers is not supported")


def normalize_doi(value: str) -> str:
    doi = unquote(value.strip()).rstrip(_TRAILING_PUNCTUATION)
    lower = doi.lower()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi.org/",
        "doi:",
    ):
        if lower.startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.strip().lower()
    if not _DOI.match(doi):
        raise InvalidIdentifier("A DOI starts with 10. followed by a prefix and a suffix")
    return doi


def normalize_arxiv(value: str) -> tuple[str, int | None]:
    """Returns (id without version, version or None)."""
    text = value.strip().rstrip(_TRAILING_PUNCTUATION)
    if text.lower().startswith("arxiv:"):
        text = text[6:]
    new = _ARXIV_NEW.match(text)
    if new:
        month = int(new["yymm"][2:])
        year = int(new["yymm"][:2])
        five_digit_era = year >= 15
        if not 1 <= month <= 12 or (year, month) < (7, 4):
            raise InvalidIdentifier("Not a valid arXiv ID (impossible year/month)")
        if five_digit_era != (len(new["seq"]) == 5):
            raise InvalidIdentifier("Not a valid arXiv ID (wrong number length for its year)")
        return f"{new['yymm']}.{new['seq']}", _version(new["v"])
    old = _ARXIV_OLD.match(text)
    if old:
        month = int(old["num"][2:4])
        if not 1 <= month <= 12:
            raise InvalidIdentifier("Not a valid arXiv ID (impossible month)")
        return f"{old['archive'].lower()}/{old['num']}", _version(old["v"])
    raise InvalidIdentifier("An arXiv ID looks like 1706.03762 or hep-th/9711200")


def _version(text: str | None) -> int | None:
    if text is None:
        return None
    version = int(text)
    if version < 1:
        raise InvalidIdentifier("arXiv versions start at v1")
    return version


def arxiv_id_from_doi(doi: str) -> str | None:
    """The arXiv ID behind an arXiv-assigned DataCite DOI (10.48550/arXiv.<id>), if any."""
    normalized = normalize_doi(doi)
    if not normalized.startswith(ARXIV_DOI_PREFIX):
        return None
    arxiv_id, _ = normalize_arxiv(normalized[len(ARXIV_DOI_PREFIX) :])
    return arxiv_id


def _from_url(url: str) -> Identifier:
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    raw_path = unquote(parts.path).lstrip("/")
    if host in ("doi.org", "dx.doi.org"):  # a DOI may legally end with "/": keep it exact
        return Identifier(IdentifierScheme.DOI, normalize_doi(raw_path))
    path = raw_path.rstrip("/")
    if host in ("arxiv.org", "export.arxiv.org"):
        for marker in ("abs/", "pdf/", "html/"):
            if path.startswith(marker):
                arxiv_id, version = normalize_arxiv(path[len(marker) :].removesuffix(".pdf"))
                return Identifier(IdentifierScheme.ARXIV, arxiv_id, version)
    if host in ("semanticscholar.org", "api.semanticscholar.org"):
        last = path.rsplit("/", 1)[-1]
        if last.lower().startswith("corpusid:"):
            return _parse_scheme(IdentifierScheme.S2_CORPUS, last.split(":", 1)[1])
        return _parse_scheme(IdentifierScheme.S2_PAPER, last)
    if host in ("openalex.org", "api.openalex.org"):
        return _parse_scheme(IdentifierScheme.OPENALEX, path.rsplit("/", 1)[-1])
    if host in ("pubmed.ncbi.nlm.nih.gov",):
        return _parse_scheme(IdentifierScheme.PMID, path.rsplit("/", 1)[-1])
    if "/doi/" in "/" + path + "/" and "10." in path:  # publisher pages: .../doi/10.x/y
        return Identifier(IdentifierScheme.DOI, normalize_doi(path[path.index("10.") :]))
    raise InvalidIdentifier(f"No paper identifier found in this link: {url}")
