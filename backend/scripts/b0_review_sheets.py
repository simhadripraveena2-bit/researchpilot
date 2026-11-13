"""Generate the two-stage blind B0 review sheets (G-MATCH, G-LATEST-DATES).

    uv run python scripts/b0_review_sheets.py          # write sheets (and new answer files)
    uv run python scripts/b0_review_sheets.py --check  # fail if anything is out of date

Stage 1 (independent ground truth): per case, the identifiers, the original recorded source
records with their paths and request URLs, primary-source URLs and record evidence. It
shows **no** AI-proposed label, expected system behaviour, AI explanation, AI notes, case
category or benchmark result, and cases appear in a fixed shuffled order (case IDs are kept).
Reviewers answer in ``stage1/*_stage1.csv``.

Stage 2 (expected policy): for a case whose Stage 1 row is complete, the AI-proposed label,
expected system behaviour, explanation and notes are revealed next to the reviewer's Stage 1
answer. At that moment the Stage 1 row is fingerprinted in ``stage1_locks.json``; any later
change to a locked Stage 1 answer makes the generator stop with an error. Reviewers answer in
``stage2/*_stage2.csv``.

The generator creates each answer CSV once (only case IDs filled in) and never writes to it
again; it never changes a label or fills a reviewer field. Output is deterministic (no
timestamps), so ``--check`` can run in CI. See docs/evaluation/review/README.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import defusedxml.ElementTree as ElementTree

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
OUT = REPO / "docs" / "evaluation" / "review"
DATASETS = {
    "G-MATCH": BACKEND / "benchmarks" / "g_match" / "b0.json",
    "G-LATEST-DATES": BACKEND / "benchmarks" / "g_latest_dates" / "b0.json",
}
DIRS = ("crossref", "biorxiv", "openalex", "semantic_scholar", "arxiv_rss")
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
STAGE1_MATCH_COLUMNS = [
    "case_id",
    "reviewer",
    "true_relationship",  # same_work | related_not_same | different | cannot_determine
    "relationship_detail",  # one of RELATIONSHIP_DETAILS
    "evidence_urls",  # primary pages opened, separated by spaces
    "notes",
    "submitted_at",  # ISO date; filling it submits the row and unlocks Stage 2
]
STAGE1_DATE_COLUMNS = [
    "case_id",
    "reviewer",
    "determinable",  # yes | not_determinable
    "true_first_public_date",  # YYYY-MM-DD (only if determinable)
    "true_event",  # one of TRUE_EVENTS (only if determinable)
    "true_manifestation",  # preprint | published | other (only if determinable)
    "evidence_urls",
    "notes",
    "submitted_at",
]
STAGE2_COLUMNS = [
    "case_id",
    "reviewer",
    "decision",  # confirm | correct | reject_case | unsure
    "corrected_label",
    "reason",
    "evidence_urls",
    "review_date",
]
RELATIONSHIPS = {"same_work", "related_not_same", "different", "cannot_determine"}
RELATIONSHIP_DETAILS = {
    "preprint_and_published",
    "versions_of_one_preprint",
    "reprint_or_translation",
    "copy_or_redeposit",
    "proceedings_and_paper",
    "comment_or_reply",
    "correction_retraction_notice",
    "component_or_supplement",
    "peer_review_document",
    "extension_or_follow_up",
    "part_of_series",
    "same_title_unrelated",
    "unrelated",
    "other",
}
DETERMINABLE = {"yes", "not_determinable"}
TRUE_EVENTS = {
    "arxiv_announcement",
    "arxiv_submission",
    "server_posting",
    "online_publication",
    "issue_publication",
    "other",
}
MANIFESTATIONS = {"preprint", "published", "other"}
DECISIONS = {"confirm", "correct", "reject_case", "unsure"}

# --- reviewer notes written by the AI assistant during preparation ---------------------
# These are questions for the human reviewer, not decisions. They point at what the
# recorded evidence cannot settle.
NOTES: dict[str, list[str]] = {
    "GM-B0-012": [
        "RELABELLED during preparation: first drafted with the ATMP DOI; the arXiv record's "
        "<arxiv:doi> is the IJTP DOI. Check the arXiv abstract page (DOI field) and confirm "
        "that the IJTP 1999 article is the same paper (a reprint of ATMP 1998), not a "
        "different text with the same title.",
    ],
    "GM-B0-023": [
        "RELABELLED during preparation, after the matcher merged the pair (risk of circular "
        "labelling). The label rests on OpenAlex listing 10.65215/pc26a033 as a location of "
        "the arXiv work; OpenAlex merges are known to be wrong sometimes.",
        "The 10.65215 DOI is registered by 'Shenzhen Medical Academy of Research and "
        "Translation' (Crossref publisher field), not by the authors or their venue, and was "
        "posted in 2025. Decide whether a third-party re-deposit counts as the same work "
        "(guideline gap: copies and re-deposits are not defined) and whether the copy is "
        "complete and faithful.",
        "Decide independently of the system output: would you merge these if no system had "
        "seen them?",
    ],
    "GM-B0-018": [
        "Both DOIs are 2025 third-party deposits (10.65215, Shenzhen Medical Academy of "
        "Research and Translation) of 'Attention Is All You Need'; see the GM-B0-023 note "
        "on copies.",
    ],
    "GM-B0-022": ["10.65215 copies; see GM-B0-023."],
    "GM-B0-015": [
        "The auto-match depends on the recorded Semantic Scholar record (strong, not "
        "decisive). Without S2 (no key or unavailable) the correct output would be a possible "
        "match; the label assumes the recording is available.",
    ],
    "GM-B0-024": [
        "Same title and author, but an AIP conference proceedings item (1999) can be a talk "
        "summary rather than the paper. Check the content (length, abstract) before accepting "
        "'same work'; 'related_not_same' is possible.",
    ],
    "GM-B0-021": [
        "Foundations and Trends issue vs book edition: usually identical text; check that "
        "the book is not an extended edition.",
    ],
    "GM-B0-028": [
        "The 2023 record has no authors; 'different' rests on 7 years' distance and the "
        "venue. Check the landing page.",
    ],
    "GM-B0-032": [
        "Both records are from Nature Reviews Methods Primers with the same title and date; "
        "the second has no authors. It may be a companion item (e.g. a summary), which would "
        "make the relationship 'related_not_same' rather than 'different'. Check the landing "
        "page. The expected output (no_match) is the same either way.",
    ],
    "GM-B0-034": [
        "Supporting Information component: 'related_not_same' with no matcher-usable link "
        "type, so the expected output is no_match.",
    ],
    "GM-B0-042": [
        "Peer-review document (author response). Guideline: related_not_same, expected "
        "no_match because is-review-of is not a matcher link.",
    ],
    "GM-B0-049": ["No update-to link; recognition rests on the title marker only."],
    "GM-B0-050": ["No update-to link and no authors on the notice."],
    "GM-B0-051": [
        "Same authors, follow-up work: 'related_not_same' is a judgement (it extends, it is "
        "not a version). Confirm.",
    ],
    "GM-B0-052": [
        "Two different GNN papers on the same topic; 'related_not_same' vs 'different' is a "
        "judgement (topic similarity only). Expected output is no_match either way.",
    ],
    "GD-B0-041": [
        "CORRECTED during preparation: first_public_kind removed (no first public date is "
        "expected).",
        "TRUTH vs POLICY: arXiv 1706.03762 was submitted Mon 2017-06-12 17:57 UTC (13:57 US "
        "Eastern, before the 14:00 cutoff), so it was most likely announced on 2017-06-13. "
        "The candidate date 2017-06-12 that OpenAlex and S2 report is probably the submission "
        "day, not the public day. The label encodes the policy output; the true first public "
        "date is not recorded in the case. Check the arXiv listing.",
    ],
    "GD-B0-042": [
        "CORRECTED during preparation: first_public_kind removed.",
        "TRUTH vs POLICY: 1512.03385 was submitted Thu 2015-12-10 19:51 UTC (14:51 US Eastern, "
        "after the cutoff), so it was most likely announced in the next listing (Mon "
        "2015-12-14). The 2015-12-10 candidate is the submission day. Check the arXiv "
        "listing.",
    ],
    "GD-B0-005": [
        "TRUTH vs POLICY: the true first public date is the 2026-11-11 announcement (see "
        "GD-B0-001); without the captured feed the system can state only the submission. The "
        "label is the policy output.",
    ],
    "GD-B0-006": ["TRUTH vs POLICY: as GD-B0-005 (announced 2026-11-11, see GD-B0-004)."],
    "GD-B0-034": [
        "Drove a rule change (R1_M1A_NOTES decision 70): development-contaminated, must "
        "never move to B1-B3.",
        "Truth assumption: the day-01 print date is a nominal issue date. Confirm on the "
        "publisher page that the article went online on 2018-11-19 and that the issue "
        "appeared later.",
    ],
    "GD-B0-035": [
        "Drove decision 70 (development-contaminated).",
        "Confirm the online date 2026-04-30 on the publisher page.",
    ],
    "GD-B0-036": [
        "Drove decision 70 (development-contaminated).",
        "Only the publisher page can tell when the article was public; 'uncertain' is the "
        "honest label from the records (print date 2017-02-01, record created 2017-07-18).",
    ],
    "GD-B0-040": [
        "TRUTH vs POLICY: the same work was on arXiv in 1997 (hep-th/9711200), but this record "
        "does not link it, so the system cannot know. The label is the policy output for this "
        "identifier alone.",
    ],
    "GD-B0-043": [
        "TRUTH vs POLICY: the true first public date is the 1997 arXiv announcement (not "
        "captured; feeds keep no history). The month-only IJTP date blocks the "
        "submission-only fallback, so the policy output is 'uncertain'.",
    ],
    "GD-B0-025": [
        "ChemRxiv records are treated as primary through Crossref (no ChemRxiv API is used). "
        "Check the posting date on the ChemRxiv page.",
    ],
    "GD-B0-026": [
        "The JAMA Pediatrics article was probably online on 2024-06-03 (the Crossref created "
        "date and the OpenAlex date), but Crossref gives only the 2024-08 issue. This does "
        "not change the first public date (medRxiv 2023-12-15).",
    ],
    "GD-B0-028": [
        "'No preprint known' means none in the recorded sources; an annotator should search "
        "for a preprint before confirming 'new publication'.",
    ],
    "GD-B0-027": [
        "'No preprint known' in the recorded sources; search before confirming. The article "
        "was retracted in 2026 (GM-B0-048); this does not change its 2019 date.",
    ],
    "GD-B0-016": [
        "The bioRxiv API 'date' of version 1 is used as the posting date; confirm it on the "
        "bioRxiv page (posting history).",
    ],
}

GENERAL_DATE_NOTE = (
    "Expected values are the documented policy applied to the recorded records. Where the "
    "policy can only state less than the truth (no captured announcement, unlinked "
    "versions), the case notes say so. B0 cases have no separate 'true first public date' "
    "field; B1 adds one (see docs/evaluation/B1_PROTOCOL.md)."
)


# --- recordings -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Recording:
    path: Path
    url: str
    status: int
    recorded: str


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO))


class Recordings:
    def __init__(self, roots: list[Path]) -> None:
        self.roots = roots
        self.by_path: dict[tuple[str, str], Recording] = {}
        for root in roots:
            for directory in DIRS:
                log = root / directory / "_recorded.json"
                if not log.exists():
                    continue
                for name, meta in sorted(json.loads(log.read_text()).items()):
                    if meta.get("constructed"):
                        continue
                    parts = urlsplit(str(meta["url"]))
                    key = (parts.netloc.lower(), unquote(parts.path).lower())
                    found = Recording(
                        root / directory / name,
                        str(meta["url"]),
                        int(meta.get("status", 200)),
                        str(meta.get("recorded", "?")),
                    )
                    # Same path, other query (e.g. a rate-limit test): a success wins.
                    known = self.by_path.get(key)
                    if known is None or (known.status != 200 and found.status == 200):
                        self.by_path[key] = found

    def get(self, host: str, path: str) -> Recording | None:
        return self.by_path.get((host, path.lower()))

    def arxiv(self, arxiv_id: str) -> Path | None:
        name = "api_" + arxiv_id.replace("/", "_") + ".xml"
        for root in self.roots:
            if (root / "arxiv" / name).exists():
                return root / "arxiv" / name
        return None


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _parts(field: Any) -> str:
    if not isinstance(field, dict) or not field.get("date-parts"):
        return "-"
    return "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(field["date-parts"][0]))


def _is_arxiv(identifier: str) -> bool:
    return not identifier.lower().startswith("10.")


def crossref_summary(rec: Recordings, doi: str) -> tuple[list[str], list[str]]:
    """Lines describing the Crossref record, and identifiers it links decisively."""
    r = rec.get("api.crossref.org", f"/works/{doi}")
    if r is None:
        return [f"Crossref `{doi}`: **not recorded**"], []
    head = f"Crossref `{doi}` (HTTP {r.status}, recorded {r.recorded}; `{_rel(r.path)}`; <{r.url}>)"
    data = _json(r.path)
    if r.status != 200 or not isinstance(data, dict):
        return [head + ": no record"], []
    m = data.get("message", {})
    authors = [a.get("family") or a.get("name") or "?" for a in m.get("author", [])]
    lines = [
        head,
        f"  - type `{m.get('type')}`{' / ' + m['subtype'] if m.get('subtype') else ''}; "
        f"title: {(m.get('title') or ['(none)'])[0][:140]}",
        f"  - authors ({len(authors)}): {', '.join(authors[:6])}"
        + (" ..." if len(authors) > 6 else ""),
        f"  - venue: {(m.get('container-title') or [m.get('publisher', '-')])[0]}; "
        f"institution: {', '.join(i.get('name', '?') for i in m.get('institution', [])) or '-'}",
        "  - dates: "
        + "; ".join(
            f"{f} {_parts(m.get(f))}"
            for f in (
                "posted",
                "published-online",
                "published-print",
                "issued",
                "accepted",
                "created",
                "indexed",
            )
            if m.get(f)
        ),
    ]
    linked: list[str] = []
    relations = m.get("relation") or {}
    shown = {
        k: sorted({str(x.get("id")) for x in v})
        for k, v in sorted(relations.items())
        if k not in ("references", "is-supplemented-by", "has-review", "is-referenced-by")
    }
    if shown:
        lines.append(
            "  - relations: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in shown.items())
        )
    for key in ("has-preprint", "is-preprint-of"):
        linked += [i.lower() for i in shown.get(key, [])]
    updates = m.get("update-to") or []
    if updates:
        lines.append(
            "  - update-to: " + "; ".join(f"{u.get('type')} of {u.get('DOI')}" for u in updates)
        )
    return lines, linked


def biorxiv_summary(rec: Recordings, doi: str) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    linked: list[str] = []
    for server in ("biorxiv", "medrxiv"):
        r = rec.get("api.biorxiv.org", f"/details/{server}/{doi}")
        if r is None:
            continue
        data = _json(r.path) or {}
        coll = data.get("collection") or []
        head = f"{server} API `{doi}` (recorded {r.recorded}; `{_rel(r.path)}`; <{r.url}>)"
        if not coll:
            lines.append(head + ": no posts")
            continue
        versions = ", ".join(f"v{c['version']} {c['date']}" for c in coll)
        pub = coll[-1].get("published")
        lines.append(f"{head}: {versions}; published: {pub or '-'}")
        lines.append(f"  - title: {coll[0].get('title', '')[:140]}")
        if pub and pub != "NA":
            linked.append(str(pub).lower())
    return lines, linked


def arxiv_summary(rec: Recordings, arxiv_id: str) -> tuple[list[str], list[str]]:
    path = rec.arxiv(arxiv_id)
    if path is None:
        return [f"arXiv API `{arxiv_id}`: **not recorded**"], []
    entry = ElementTree.parse(path).getroot().find("a:entry", ATOM)
    if entry is None:
        return [f"arXiv API `{arxiv_id}` (`{_rel(path)}`): no entry"], []

    def text(tag: str) -> str:
        found = entry.find(tag, ATOM)
        return (found.text or "").strip() if found is not None and found.text else "-"

    prim = entry.find("arxiv:primary_category", ATOM)
    authors = [a.findtext("a:name", "", ATOM) for a in entry.findall("a:author", ATOM)]
    doi = text("arxiv:doi")
    lines = [
        f"arXiv API `{arxiv_id}` (`{_rel(path)}`; "
        f"<https://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1>)",
        f"  - title: {re.sub(r'\\s+', ' ', text('a:title'))[:140]}",
        f"  - authors ({len(authors)}): {', '.join(authors[:6])}"
        + (" ..." if len(authors) > 6 else ""),
        f"  - published (v1 submission) {text('a:published')}; updated {text('a:updated')}; "
        f"latest {text('a:id').rsplit('/', 1)[-1]}; primary "
        f"{prim.get('term') if prim is not None else '-'}; DOI {doi}",
    ]
    return lines, ([doi.lower()] if doi != "-" else [])


def aggregator_summary(rec: Recordings, identifier: str) -> list[str]:
    lines = []
    if _is_arxiv(identifier):
        oa_path, s2_path = (
            f"/works/doi:10.48550/arxiv.{identifier}",
            f"/graph/v1/paper/arxiv:{identifier}",
        )
    else:
        oa_path, s2_path = f"/works/doi:{identifier}", f"/graph/v1/paper/doi:{identifier}"
    oa = rec.get("api.openalex.org", oa_path)
    if oa is not None:
        d = _json(oa.path) or {}
        lines.append(
            f"OpenAlex (`{_rel(oa.path)}`, HTTP {oa.status}, <{oa.url}>): publication_date "
            f"{d.get('publication_date', '-')}, created_date {d.get('created_date', '-')}"
        )
    s2 = rec.get("api.semanticscholar.org", s2_path)
    if s2 is not None:
        d = _json(s2.path) or {}
        ids = d.get("externalIds") or {}
        lines.append(
            f"Semantic Scholar (`{_rel(s2.path)}`, HTTP {s2.status}, <{s2.url}>): "
            "publicationDate "
            f"{d.get('publicationDate', '-')}; ids "
            + ", ".join(f"{k}={v}" for k, v in sorted(ids.items()) if k in ("ArXiv", "DOI"))
        )
    if not lines:
        lines.append("OpenAlex / Semantic Scholar: not recorded (not available to the system)")
    return lines


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def title_of(rec: Recordings, identifier: str) -> str | None:
    """The title the system of record gives (arXiv, preprint server, else Crossref)."""
    lines, _ = records(rec, identifier)
    for line in lines:
        found = re.search(r"title: (.+)$", line)
        if found and found.group(1) != "(none)":
            return found.group(1).strip()
    return None


def records(rec: Recordings, identifier: str) -> tuple[list[str], list[str]]:
    if _is_arxiv(identifier):
        lines, linked = arxiv_summary(rec, identifier)
    else:
        lines, linked = [], []
        if identifier.lower().startswith("10.1101/"):
            lines, linked = biorxiv_summary(rec, identifier)
        cr, cr_linked = crossref_summary(rec, identifier)
        if not (identifier.lower().startswith("10.1101/") and "not recorded" in cr[0]):
            lines += cr
        linked += cr_linked
    lines += aggregator_summary(rec, identifier)
    return lines, sorted(set(linked) - {identifier.lower()})


def feed_lines(rec: Recordings, feeds: list[str], ids: list[str]) -> list[str]:
    out = []
    for feed in feeds:
        r = rec.get("rss.arxiv.org", f"/rss/{feed}")
        if r is None:
            out.append(f"arXiv RSS {feed}: **not recorded**")
            continue
        text = r.path.read_text()
        day = re.search(r"<pubDate>([^<]+)</pubDate>", text)
        out.append(f"arXiv RSS `{feed}` (`{_rel(r.path)}`, pubDate {day.group(1) if day else '-'})")
        for item in re.findall(r"<item>(.*?)</item>", text, re.S):
            found = re.search(r"oai:arXiv.org:([^<]+)", item)
            kind = re.search(r"announce_type>([^<]+)<", item)
            if found and any(found.group(1).startswith(i + "v") for i in ids):
                out.append(f"  - {found.group(1)}: announce_type {kind.group(1) if kind else '?'}")
    return out


# --- shared case content ---------------------------------------------------------------------


class ReviewError(SystemExit):
    """Reviewer files are inconsistent; nothing is written."""


def _ids(c: dict[str, Any], match: bool) -> list[str]:
    return [c["a"], c["b"]] if match else list(c["identifiers"])


def primary_urls(rec: Recordings, identifier: str) -> list[str]:
    """Pages a reviewer opens to establish the truth (not the recorded API responses)."""
    if _is_arxiv(identifier):
        return [
            f"https://arxiv.org/abs/{identifier} (abstract page, submission history)",
            "https://arxiv.org/list/<primary category>/... (announcement listings)",
        ]
    urls = [f"https://doi.org/{identifier} (publisher / landing page)"]
    if identifier.lower().startswith("10.1101/"):
        for server in ("biorxiv", "medrxiv"):
            r = rec.get("api.biorxiv.org", f"/details/{server}/{identifier}")
            if r is not None and (_json(r.path) or {}).get("collection"):
                urls.append(f"https://www.{server}.org/content/{identifier} (posting history)")
    return urls


def record_block(c: dict[str, Any], rec: Recordings, match: bool) -> tuple[list[str], list[str]]:
    """The recorded source records of a case, as neutral evidence. Returns lines and the
    records that are missing."""
    ids = _ids(c, match)
    lines = ["- **Primary sources to check:**"]
    for identifier in ids:
        lines += [f"  - {url}" for url in primary_urls(rec, identifier)]
    lines.append(
        "- **Original source records (recorded API responses: what the system can see, "
        "not the ground truth):**"
    )
    missing: list[str] = []
    cited: set[str] = set()
    for identifier in ids:
        rec_lines, linked = records(rec, identifier)
        lines += [f"  - {line}" if not line.startswith("  ") else f"  {line}" for line in rec_lines]
        missing += [line for line in rec_lines if "not recorded**" in line]
        if not match:
            cited |= set(linked) - {i.lower() for i in ids}
    for identifier in sorted(cited):
        rec_lines, _ = records(rec, identifier)
        lines.append(f"  - (record cited as a version by a record above) `{identifier}`:")
        lines += [f"    - {line.strip().removeprefix('- ')}" for line in rec_lines]
        missing += [line for line in rec_lines if "not recorded**" in line]
    if not match and c.get("capture_feeds"):
        lines += [
            f"  - {line}" if not line.startswith("  ") else f"  {line}"
            for line in feed_lines(rec, c["capture_feeds"], ids)
        ]
    if match:
        titles = {i: title_of(rec, i) for i in ids}
        if all(titles.values()) and len({_norm(t) for t in titles.values() if t}) > 1:
            lines.append("- **Note:** the titles in the two records are not identical.")
    return lines, missing


def match_label(c: dict[str, Any]) -> str:
    e = c["expected"]
    return f"{e['relationship']} / {e['outcome']}"


def date_label(c: dict[str, Any]) -> str:
    e = c["expected"]
    return f"{e.get('first_public_date') or 'none'} ({e.get('basis') or '-'}), {e['confidence']}"


def policy_block(c: dict[str, Any], match: bool) -> list[str]:
    """Everything Stage 1 hides: the AI-proposed label and expected system behaviour."""
    e = c["expected"]
    lines = [
        f"- **Category (AI):** {c['category']}"
        + (" (adversarial)" if c.get("adversarial") else ""),
        f"- **AI-proposed label:** {match_label(c) if match else date_label(c)} "
        f"(status `{c['labels']['status']}`, guideline `{c['labels']['guideline']}`)",
    ]
    if match:
        lines.append(f"- **Ground truth (AI-proposed):** `{e['relationship']}`")
        lines.append(
            f"- **Expected system behaviour:** outcome `{e['outcome']}`; auto-merge allowed: "
            f"{'yes' if e['auto_merge_allowed'] else 'no'}; user confirmation required: "
            f"{'yes' if e['user_confirmation_required'] else 'no'}; decisive evidence: "
            f"{'yes' if e['decisive_evidence'] else 'no'}; both orders must agree; a merge "
            "must be reversible and its rejection sticky"
        )
    else:
        extra = []
        if e.get("first_public_kind"):
            extra.append(f"first public manifestation `{e['first_public_kind']}`")
        if e.get("candidate_public_date"):
            extra.append(f"unconfirmed candidate {e['candidate_public_date']}")
        if e.get("window"):
            w = e["window"]
            window = w if isinstance(w, str) else f"{w[0]}..{w[1]}"
            extra.append(f"window {window} -> release type `{e.get('release_type')}`")
        lines.append(
            "- **Ground truth (AI-proposed):** not recorded separately in B0 (the B0 label is "
            "the expected system behaviour; compare it with your Stage 1 truth)"
        )
        lines.append(
            f"- **Expected system behaviour:** first public date "
            f"{e.get('first_public_date') or 'none'} (basis {e.get('basis') or '-'}), "
            f"confidence `{e['confidence']}`" + ("; " + "; ".join(extra) if extra else "")
        )
    lines += [f"- **Explanation (AI):** {c['explanation']}", "- **Evidence (AI-cited):**"]
    lines += [f"  - {item}" for item in c["evidence"]]
    flags = list(NOTES.get(c["id"], []))
    if match and e["relationship"] == "same_work" and e["outcome"] != "auto_match":
        flags.append(
            "TRUTH vs POLICY: AI-proposed truth is same_work; the expected output is a possible "
            "match because no link exists in the records."
        )
    if match and e["relationship"] == "related_not_same" and e["outcome"] == "no_match":
        flags.append(
            "TRUTH vs POLICY: related_not_same without a matcher-usable link; the expected "
            "output is no_match."
        )
    if not match:
        flags.append(GENERAL_DATE_NOTE)
    lines.append("- **AI notes for the reviewer:**")
    lines += [f"  - {f}" for f in flags] or ["  - none"]
    return lines


# --- answer files ------------------------------------------------------------------------------


def _read_csv(path: Path, columns: list[str], ids: list[str]) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise ReviewError(f"{path}: columns must be {columns}, found {reader.fieldnames}")
        rows = list(reader)
    found = [r["case_id"] for r in rows]
    if sorted(found) != sorted(set(found)) or set(found) - set(ids):
        raise ReviewError(f"{path}: duplicate or unknown case ids")
    return {r["case_id"]: {k: (v or "").strip() for k, v in r.items()} for r in rows}


def _check_values(
    path: Path, case_id: str, row: dict[str, str], allowed: dict[str, set[str]]
) -> None:
    for column, values in allowed.items():
        if row.get(column) and row[column] not in values:
            raise ReviewError(
                f"{path}: {case_id}: {column}={row[column]!r} not in {sorted(values)}"
            )


def stage1_complete(row: dict[str, str] | None, match: bool, path: Path) -> bool:
    """A Stage 1 row is submitted when ``submitted_at`` is set; it must then be complete."""
    if not row or not row.get("submitted_at"):
        return False
    case_id = row["case_id"]
    missing = [k for k in ("reviewer", "evidence_urls") if not row.get(k)]
    if match:
        missing += [k for k in ("true_relationship", "relationship_detail") if not row.get(k)]
    elif row.get("determinable") == "yes":
        missing += [
            k
            for k in ("true_first_public_date", "true_event", "true_manifestation")
            if not row.get(k)
        ]
    elif row.get("determinable") != "not_determinable":
        missing.append("determinable")
    if missing:
        raise ReviewError(f"{path}: {case_id} is submitted but lacks {missing}")
    if not match and row.get("determinable") == "yes":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["true_first_public_date"]):
            raise ReviewError(f"{path}: {case_id}: true_first_public_date must be YYYY-MM-DD")
    return True


def fingerprint(row: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()


def blank_csv(columns: list[str], ids: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, columns, lineterminator="\n")
    writer.writeheader()
    for case_id in ids:
        writer.writerow({"case_id": case_id})
    return buffer.getvalue()


def presentation_order(ids: list[str]) -> list[str]:
    """Fixed shuffled order: consecutive IDs share a category, so ID order would hint at
    the AI's categories."""
    return sorted(ids, key=lambda i: hashlib.sha256(f"b0-review:{i}".encode()).hexdigest())


# --- sheets ------------------------------------------------------------------------------------


def stage1_sheet(
    benchmark: str,
    data: dict[str, Any],
    rec: Recordings,
    answers: dict[str, dict[str, str]],
    csv_path: Path,
    out: Path,
) -> str:
    match = benchmark == "G-MATCH"
    cases = {c["id"]: c for c in (data.get("match_cases") or data.get("date_cases") or [])}
    submitted = sum(1 for a in answers.values() if a.get("submitted_at"))
    if match:
        task = [
            "Decide, from the primary sources, how the two identifiers are related.",
            "",
            f"- `true_relationship`: {', '.join(sorted(RELATIONSHIPS))}",
            f"- `relationship_detail`: {', '.join(sorted(RELATIONSHIP_DETAILS))}",
        ]
    else:
        task = [
            "Decide, from the primary sources, when the work (all its versions) first became "
            "publicly available.",
            "",
            f"- `determinable`: {', '.join(sorted(DETERMINABLE))}. Use `not_determinable` when "
            "the sources do not establish a day; leave the date fields empty then.",
            "- `true_first_public_date`: YYYY-MM-DD",
            f"- `true_event`: {', '.join(sorted(TRUE_EVENTS))}",
            f"- `true_manifestation`: {', '.join(sorted(MANIFESTATIONS))}",
        ]
    lines = [
        f"# {benchmark} B0 review - Stage 1: independent ground truth",
        "",
        "Generated by `backend/scripts/b0_review_sheets.py`. Do not edit by hand.",
        "",
        "This sheet deliberately shows **no AI-proposed label, expected system behaviour, "
        "explanation, category or benchmark result**. Do not open the Stage 2 sheets, the "
        "benchmark datasets (`backend/benchmarks/`) or the reports (`docs/evaluation/reports/`) "
        "before submitting Stage 1 for a case.",
        "",
        *task,
        "",
        f"Record answers in `{csv_path.relative_to(out)}` (one row per case; `evidence_urls` "
        "are the primary pages you opened; set `submitted_at` to the date when the row is "
        "final: a submitted row is locked once Stage 2 is revealed).",
        "",
        f"Submitted: **{submitted} / {len(cases)}**. Cases are listed in a fixed shuffled order.",
        "",
    ]
    for case_id in presentation_order(list(cases)):
        c = cases[case_id]
        ids = _ids(c, match)
        block, missing = record_block(c, rec, match)
        lines += [
            f"## {case_id}",
            "",
            f"- **Identifiers:** {', '.join(f'`{i}`' for i in ids)}"
            + (
                f"; arXiv announcement feeds captured for this case: "
                f"{', '.join(c['capture_feeds'])}"
                if c.get("capture_feeds")
                else ""
            ),
            *block,
        ]
        if missing:
            lines += [f"- **Missing record:** {m.strip()}" for m in missing]
        status = "submitted" if answers.get(case_id, {}).get("submitted_at") else "open"
        lines += [f"- **Stage 1 status:** {status}", ""]
    return "\n".join(lines)


def stage2_sheet(
    benchmark: str,
    data: dict[str, Any],
    rec: Recordings,
    stage1: dict[str, dict[str, str]],
    revealed: set[str],
    stage2: dict[str, dict[str, str]],
    csv_path: Path,
    out: Path,
) -> str:
    match = benchmark == "G-MATCH"
    cases = {c["id"]: c for c in (data.get("match_cases") or data.get("date_cases") or [])}
    decided = sum(1 for r in stage2.values() if r.get("decision"))
    lines = [
        f"# {benchmark} B0 review - Stage 2: expected-policy assessment",
        "",
        "Generated by `backend/scripts/b0_review_sheets.py`. Do not edit by hand.",
        "",
        "A case appears here **only after its Stage 1 row is submitted**; its Stage 1 answer is "
        "then locked (`stage1_locks.json`). **All labels below are AI-proposed** "
        "(`labels.status = ai_proposed`); none is human-reviewed until a decision is recorded "
        "and a person updates the dataset.",
        "",
        "Two different questions:",
        "",
        "- **Ground truth** (Stage 1): what is true, from the primary sources.",
        "- **Expected system behaviour** (this stage): does the AI-proposed expectation follow "
        "from the documented guideline (`docs/evaluation/G_MATCH_GUIDELINES.md`, "
        "`G_LATEST_DATES_GUIDELINES.md`) and the records available to the system? It may "
        "legitimately differ from the truth (see the TRUTH vs POLICY notes).",
        "",
        f"Record decisions in `{csv_path.relative_to(out)}`: `decision` is one of "
        f"{', '.join(sorted(DECISIONS))}; `corrected_label` only for `correct`; `reason`; "
        "`evidence_urls`; `review_date`.",
        "",
        f"Revealed: **{len(revealed)} / {len(cases)}**; decided: **{decided} / {len(cases)}**.",
        "",
    ]
    for case_id in sorted(cases):
        if case_id not in revealed:
            lines += [f"## {case_id}", "", "- Locked: Stage 1 not submitted.", ""]
            continue
        c = cases[case_id]
        s1 = stage1[case_id]
        if match:
            truth = f"`{s1['true_relationship']}` ({s1['relationship_detail']})"
        elif s1["determinable"] == "yes":
            truth = (
                f"{s1['true_first_public_date']} ({s1['true_event']}, {s1['true_manifestation']})"
            )
        else:
            truth = "not determinable"
        block, _ = record_block(c, rec, match)
        d = stage2.get(case_id, {})
        lines += [
            f"## {case_id}",
            "",
            f"- **Identifiers:** {', '.join(f'`{i}`' for i in _ids(c, match))}",
            f"- **Your Stage 1 ground truth (locked):** {truth}; by `{s1['reviewer']}` on "
            f"{s1['submitted_at']}; evidence: {s1['evidence_urls']}"
            + (f"; notes: {s1['notes']}" if s1.get("notes") else ""),
            *policy_block(c, match),
            *block,
            "- **Stage 2 decision:** "
            + (
                f"**{d['decision']}** by `{d.get('reviewer', '')}` on {d.get('review_date', '')}"
                + (f"; corrected label: {d['corrected_label']}" if d.get("corrected_label") else "")
                + f"; reason: {d.get('reason', '')}"
                if d.get("decision")
                else "_(blank: record in the Stage 2 CSV)_"
            ),
            "",
        ]
    return "\n".join(lines)


# --- build ---------------------------------------------------------------------------------------


def build(out: Path = OUT, datasets: dict[str, Path] = DATASETS) -> dict[Path, str]:
    """Everything the generator would write. Never includes an existing answer CSV."""
    files: dict[Path, str] = {}
    locks_path = out / "stage1_locks.json"
    locks: dict[str, str] = json.loads(locks_path.read_text()) if locks_path.exists() else {}
    new_locks = dict(locks)
    for benchmark, path in datasets.items():
        match = benchmark == "G-MATCH"
        data = json.loads(path.read_text())
        rec = Recordings([(path.parent / r).resolve() for r in data["recordings"]])
        cases = data.get("match_cases") or data.get("date_cases") or []
        ids = [c["id"] for c in cases]
        stem = benchmark.lower().replace("-", "_")
        s1_path = out / "stage1" / f"{stem}_b0_stage1.csv"
        s2_path = out / "stage2" / f"{stem}_b0_stage2.csv"
        s1_cols = STAGE1_MATCH_COLUMNS if match else STAGE1_DATE_COLUMNS
        stage1 = _read_csv(s1_path, s1_cols, ids)
        stage2 = _read_csv(s2_path, STAGE2_COLUMNS, ids)
        allowed = (
            {"true_relationship": RELATIONSHIPS, "relationship_detail": RELATIONSHIP_DETAILS}
            if match
            else {
                "determinable": DETERMINABLE,
                "true_event": TRUE_EVENTS,
                "true_manifestation": MANIFESTATIONS,
            }
        )
        revealed: set[str] = set()
        for case_id in ids:
            row = stage1.get(case_id)
            if row:
                _check_values(s1_path, case_id, row, allowed)
            if case_id in locks:
                if row is None or fingerprint(row) != locks[case_id]:
                    raise ReviewError(
                        f"{s1_path}: Stage 1 answer for {case_id} changed after Stage 2 was "
                        "revealed; restore it (see git history). Locked answers cannot change."
                    )
                revealed.add(case_id)
            elif stage1_complete(row, match, s1_path):
                assert row is not None
                new_locks[case_id] = fingerprint(row)
                revealed.add(case_id)
        for case_id, row in stage2.items():
            _check_values(s2_path, case_id, row, {"decision": DECISIONS})
            if any(v for k, v in row.items() if k != "case_id") and case_id not in revealed:
                raise ReviewError(f"{s2_path}: {case_id} has a Stage 2 answer before Stage 1")
        if not s1_path.exists():
            files[s1_path] = blank_csv(s1_cols, presentation_order(ids))
        if not s2_path.exists():
            files[s2_path] = blank_csv(STAGE2_COLUMNS, ids)
        files[out / "stage1" / f"{stem.upper()}_B0_STAGE1.md"] = stage1_sheet(
            benchmark, data, rec, stage1, s1_path, out / "stage1"
        )
        files[out / "stage2" / f"{stem.upper()}_B0_STAGE2.md"] = stage2_sheet(
            benchmark, data, rec, stage1, revealed, stage2, s2_path, out / "stage2"
        )
    files[locks_path] = json.dumps(dict(sorted(new_locks.items())), indent=1) + "\n"
    return files


def write(files: dict[Path, str]) -> None:
    for path, text in files.items():
        if path.suffix == ".csv" and path.exists():
            raise ReviewError(f"refusing to overwrite reviewer file {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if sheets are stale")
    args = parser.parse_args()
    files = build()
    if args.check:
        stale = [p for p, text in files.items() if not p.exists() or p.read_text() != text]
        if stale:
            print("out of date:", *[_rel(p) for p in stale], sep="\n  ")
            sys.exit(1)
        print("review sheets up to date")
        return
    write(files)
    for path in files:
        print(_rel(path))


if __name__ == "__main__":
    main()
