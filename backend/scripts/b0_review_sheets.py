"""Generate the B0 review sheets (G-MATCH, G-LATEST-DATES) for human reviewers.

    uv run python scripts/b0_review_sheets.py          # write the sheets
    uv run python scripts/b0_review_sheets.py --check  # fail if they are out of date

For every case the sheet shows the AI-proposed label, the expected system behaviour, the
original recorded source records (summarised from the files themselves, with their paths),
the evidence and provenance, and known ambiguities or missing evidence. It never changes a
label: reviewers record decisions in ``docs/evaluation/review/*_decisions.csv`` (created
empty once, never overwritten). A label changes only when a person edits the dataset
(``benchmarks/build_b0.py``) after review - see docs/evaluation/review/README.md.

Output is deterministic (no timestamps), so ``--check`` can run in CI.
"""

from __future__ import annotations

import argparse
import csv
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
DECISION_COLUMNS = [
    "case_id",
    "ai_proposed_label",
    "reviewer",
    "decision",  # confirm | correct | reject_case | unsure
    "corrected_label",
    "reason",
    "evidence_checked",  # primary pages actually opened (URLs)
    "review_date",
]
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
    head = f"Crossref `{doi}` (HTTP {r.status}, recorded {r.recorded}; `{_rel(r.path)}`)"
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
        head = f"{server} API `{doi}` (recorded {r.recorded}; `{_rel(r.path)}`)"
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
        f"arXiv API `{arxiv_id}` (`{_rel(path)}`)",
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
            f"OpenAlex (`{_rel(oa.path)}`, HTTP {oa.status}): publication_date "
            f"{d.get('publication_date', '-')}, created_date {d.get('created_date', '-')}"
        )
    s2 = rec.get("api.semanticscholar.org", s2_path)
    if s2 is not None:
        d = _json(s2.path) or {}
        ids = d.get("externalIds") or {}
        lines.append(
            f"Semantic Scholar (`{_rel(s2.path)}`, HTTP {s2.status}): publicationDate "
            f"{d.get('publicationDate', '-')}; ids "
            + ", ".join(f"{k}={v}" for k, v in sorted(ids.items()) if k in ("ArXiv", "DOI"))
        )
    if not lines:
        lines.append(
            "OpenAlex / Semantic Scholar: not recorded (treated as unavailable in the run)"
        )
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


# --- sheets ----------------------------------------------------------------------------------


def load_decisions(path: Path, ids: list[str]) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    unknown = sorted({r["case_id"] for r in rows} - set(ids))
    if unknown:
        raise SystemExit(f"{path}: unknown case ids {unknown}")
    bad = sorted({r["decision"] for r in rows if r["decision"]} - DECISIONS)
    if bad:
        raise SystemExit(f"{path}: unknown decisions {bad} (allowed: {sorted(DECISIONS)})")
    return {r["case_id"]: r for r in rows}


def match_label(c: dict[str, Any]) -> str:
    e = c["expected"]
    return f"{e['relationship']} / {e['outcome']}"


def date_label(c: dict[str, Any]) -> str:
    e = c["expected"]
    return f"{e.get('first_public_date') or 'none'} ({e.get('basis') or '-'}), {e['confidence']}"


def _review_lines(decision: dict[str, str] | None) -> list[str]:
    if not decision or not decision.get("decision"):
        return [
            "- **Review status:** not reviewed (label is AI-proposed)",
            "- **Reviewer decision:** _(blank: record in the decisions CSV)_",
        ]
    return [
        f"- **Review status:** reviewed by `{decision['reviewer']}` on "
        f"{decision['review_date']}: **{decision['decision']}**",
        f"- **Reviewer decision:** {decision['corrected_label'] or '(label confirmed)'}; "
        f"reason: {decision['reason']}; checked: {decision['evidence_checked']}",
    ]


def sheet(benchmark: str, data: dict[str, Any], rec: Recordings, decisions_path: Path) -> str:
    match = benchmark == "G-MATCH"
    cases = data.get("match_cases", []) if match else data.get("date_cases", [])
    decisions = load_decisions(decisions_path, [c["id"] for c in cases])
    reviewed = sum(1 for d in decisions.values() if d.get("decision"))
    lines = [
        f"# {benchmark} B0 review sheet ({data['version']})",
        "",
        "Generated by `backend/scripts/b0_review_sheets.py` from "
        f"`{_rel(DATASETS[benchmark])}` and the recorded responses. Do not edit by hand.",
        "",
        "**Every label on this sheet is AI-proposed** (`labels.status = ai_proposed`, "
        "`proposed_by = ai-assistant`). None is human-reviewed or expert-validated until a "
        "reviewer decision is recorded in "
        f"`{_rel(decisions_path)}` and a person updates the dataset.",
        "",
        f"Review progress: **{reviewed} / {len(cases)}** cases have a recorded decision.",
        "",
        "How to review: docs/evaluation/review/README.md. Open the primary pages (arXiv "
        "abstract page and listing, preprint-server page, publisher landing page); the "
        "recorded API responses below are what the system saw, not the ground truth.",
        "",
    ]
    if not match:
        lines += [GENERAL_DATE_NOTE, ""]
    for c in cases:
        ids = [c["a"], c["b"]] if match else c["identifiers"]
        e = c["expected"]
        lines += [
            f"## {c['id']} - {c['category']}" + (" (adversarial)" if c.get("adversarial") else ""),
            "",
            f"- **Identifiers:** {', '.join(f'`{i}`' for i in ids)}"
            + (
                f"; captured feeds: {', '.join(c['capture_feeds'])}"
                if c.get("capture_feeds")
                else ""
            ),
            f"- **AI-proposed label:** {match_label(c) if match else date_label(c)} "
            f"(status `{c['labels']['status']}`, guideline `{c['labels']['guideline']}`)",
        ]
        if match:
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
                f"- **Expected system behaviour:** first public date "
                f"{e.get('first_public_date') or 'none'} (basis {e.get('basis') or '-'}), "
                f"confidence `{e['confidence']}`" + ("; " + "; ".join(extra) if extra else "")
            )
        lines += [f"- **Explanation (AI):** {c['explanation']}", "- **Evidence (AI-cited):**"]
        lines += [f"  - {item}" for item in c["evidence"]]
        lines.append("- **Original source records (as recorded):**")
        missing = []
        followed: set[str] = set()
        for identifier in ids:
            rec_lines, linked = records(rec, identifier)
            lines += [
                f"  - {line}" if not line.startswith("  ") else f"  {line}" for line in rec_lines
            ]
            missing += [line for line in rec_lines if "not recorded**" in line]
            if not match:
                followed |= set(linked) - {i.lower() for i in ids}
        for identifier in sorted(followed):
            rec_lines, _ = records(rec, identifier)
            lines.append(f"  - (linked version, fetched by ingestion) `{identifier}`:")
            lines += [f"    - {line.strip().removeprefix('- ')}" for line in rec_lines]
            missing += [line for line in rec_lines if "not recorded**" in line]
        if not match and c.get("capture_feeds"):
            lines += [
                f"  - {line}" if not line.startswith("  ") else f"  {line}"
                for line in feed_lines(rec, c["capture_feeds"], ids)
            ]
        flags = list(NOTES.get(c["id"], []))
        if match and e["relationship"] == "same_work" and e["outcome"] != "auto_match":
            flags.append(
                "TRUTH vs POLICY: ground truth is same_work; the expected output is a possible "
                "match because no link exists in the records."
            )
        if match and e["relationship"] == "related_not_same" and e["outcome"] == "no_match":
            flags.append(
                "TRUTH vs POLICY: related_not_same without a matcher-usable link; the "
                "expected output is no_match."
            )
        if match:
            titles = {i: title_of(rec, i) for i in ids}
            if all(titles.values()) and len({_norm(t) for t in titles.values() if t}) > 1:
                flags.append(
                    "TITLES DIFFER between the two records (retitled or different work): "
                    + " | ".join(f"`{i}`: {t}" for i, t in titles.items())
                    + (
                        ". If same work, consider category explicit_link_different_title."
                        if e["relationship"] == "same_work"
                        and c["category"] != "explicit_link_different_title"
                        else ""
                    )
                )
        flags += [f"MISSING EVIDENCE: {m.strip()}" for m in missing]
        lines.append("- **Ambiguity / missing evidence:**")
        lines += [f"  - {f}" for f in flags] or ["  - none noted (reviewer to confirm)"]
        lines += [*_review_lines(decisions.get(c["id"])), ""]
    return "\n".join(lines)


def empty_decisions(cases: list[dict[str, Any]], benchmark: str) -> str:
    from io import StringIO

    buffer = StringIO()
    writer = csv.DictWriter(buffer, DECISION_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for c in cases:
        label = match_label(c) if benchmark == "G-MATCH" else date_label(c)
        writer.writerow({"case_id": c["id"], "ai_proposed_label": label})
    return buffer.getvalue()


def build() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for benchmark, path in DATASETS.items():
        data = json.loads(path.read_text())
        rec = Recordings([(path.parent / r).resolve() for r in data["recordings"]])
        stem = benchmark.lower().replace("-", "_")
        decisions = OUT / f"{stem}_b0_decisions.csv"
        cases = data.get("match_cases") or data.get("date_cases") or []
        if not decisions.exists():
            out[decisions] = empty_decisions(cases, benchmark)
        out[OUT / f"{stem.upper()}_B0_REVIEW.md"] = sheet(benchmark, data, rec, decisions)
    return out


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
    OUT.mkdir(parents=True, exist_ok=True)
    for path, text in files.items():
        path.write_text(text)
        print(_rel(path))


if __name__ == "__main__":
    main()
