"""Builds the B0 dataset files from the case tables below (keeps the JSON reviewable).

Labels are AI-proposed (``ai_proposed``): they state the evidence in the recorded source
records that justifies them, and await review by a team member against the primary pages
(EVALUATION_FRAMEWORK §2a). They are never gold.

    uv run python benchmarks/build_b0.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
LABELS = {
    "status": "ai_proposed",
    "proposed_by": "ai-assistant",
    "annotators": [],
    "adjudicator": None,
    "approved_by": None,
}
RECORDINGS = ["../recordings", "../../tests/fixtures/sources"]

SAME, REL, DIFF = "same_work", "related_not_same", "different"
AUTO, POSS, REL_O, NONE = "auto_match", "possible_match", "related_not_same", "no_match"

# (category, adversarial, a, b, relationship, outcome, decisive, explanation, evidence)
MATCH = [
    # --- preprint and its journal version, explicit (decisive) link -------------------------
    *[
        (
            "preprint_journal",
            False,
            pre,
            pub,
            SAME,
            AUTO,
            True,
            "The bioRxiv preprint and the journal article are one work: bioRxiv itself records "
            "the publication.",
            [
                f"bioRxiv /pubs (2024-06-03) lists {pre} as published as {pub}",
                "bioRxiv /details for the preprint carries the published DOI",
            ],
        )
        for pre, pub in [
            ("10.1101/2023.10.03.560658", "10.7554/elife.92909"),
            ("10.1101/2023.08.22.554292", "10.7554/elife.93686.3"),
            ("10.1101/2023.07.10.548412", "10.7554/elife.89017.3"),
            ("10.1101/2023.05.26.542436", "10.7554/elife.91288.3"),
            ("10.1101/2023.08.14.553247", "10.7554/elife.91924.3"),
            ("10.1101/2022.09.22.507167", "10.7554/elife.90972.3"),
            ("10.1101/2021.10.22.465218", "10.1093/plphys/kiae255"),
            ("10.1101/2023.07.27.550891", "10.1038/s42003-024-06342-y"),
            ("10.1101/2021.12.07.471480", "10.1038/s41598-024-63226-1"),
            ("10.1101/2023.10.02.560470", "10.1371/journal.pbio.3002664"),
            ("10.1101/2022.10.22.513336", "10.7554/elife.87434"),
        ]
    ],
    (
        "preprint_journal",
        False,
        "hep-th/9711200",
        "10.1023/a:1026654312961",
        SAME,
        AUTO,
        True,
        "Maldacena's arXiv preprint and its International Journal of Theoretical Physics (1999) "
        "printing: the arXiv record's author-supplied DOI is the IJTP DOI. (Label corrected on "
        "evidence review: the first draft named the ATMP DOI, which the arXiv record does not "
        "carry; see ATMP below.)",
        ["arXiv entry hep-th/9711200 <arxiv:doi> = 10.1023/A:1026654312961"],
    ),
    (
        "preprint_journal",
        False,
        "10.26434/chemrxiv.15006367/v1",
        "10.1021/acs.jcim.6c01012",
        SAME,
        AUTO,
        True,
        "ChemRxiv preprint and its JCIM article: Crossref links them in both directions.",
        [
            "Crossref 10.1021/acs.jcim.6c01012 relation has-preprint 10.26434/chemrxiv.15006367/v1",
            "Crossref 10.26434/chemrxiv.15006367/v1 relation is-preprint-of the JCIM DOI",
        ],
    ),
    (
        "explicit_link_different_title",
        False,
        "10.1101/2023.12.14.23299828",
        "10.1001/jamapediatrics.2024.1379",
        SAME,
        AUTO,
        True,
        "The medRxiv preprint was retitled for JAMA Pediatrics ('Longitudinal associations between "
        "weight indices, cognition...' vs 'Weight Indices, Cognition, and Mental Health From "
        "Childhood...'); the explicit link decides, not the title.",
        [
            "Crossref JAMA record relation has-preprint 10.1101/2023.12.14.23299828",
            "Crossref medRxiv record relation is-preprint-of 10.1001/jamapediatrics.2024.1379",
        ],
    ),
    (
        "preprint_journal",
        False,
        "1512.03385",
        "10.1109/cvpr.2016.90",
        SAME,
        AUTO,
        False,
        "ResNet on arXiv and at CVPR 2016 are one work. No authoritative version link exists "
        "(the arXiv record has no DOI); the Semantic Scholar record lists both identifiers "
        "(strong evidence), with the same title and authors.",
        [
            "Semantic Scholar record for ARXIV:1512.03385 lists DOI 10.1109/CVPR.2016.90",
            "identical title; same four authors",
        ],
    ),
    # --- versions of one preprint -----------------------------------------------------------
    (
        "preprint_versions",
        False,
        "10.7554/elife.89679",
        "10.7554/elife.89679.2",
        SAME,
        AUTO,
        False,
        "eLife reviewed preprint and its version 2: one work. Crossref declares them the same.",
        [
            "Crossref 10.7554/elife.89679 relation is-same-as 10.7554/eLife.89679.2",
            "identical title and 14 authors",
        ],
    ),
    (
        "preprint_versions",
        False,
        "10.7554/elife.87434",
        "10.7554/elife.87434.3",
        SAME,
        AUTO,
        False,
        "eLife article and its version of record (.3): one work (is-same-as).",
        ["Crossref 10.7554/elife.87434 relation is-same-as 10.7554/eLife.87434.3"],
    ),
    (
        "preprint_versions",
        False,
        "10.65215/ysbyhc05",
        "10.65215/r5bs2d54",
        SAME,
        AUTO,
        False,
        "Two deposits of the same posted copy of 'Attention Is All You Need'; Crossref declares "
        "one a version of the other.",
        [
            "Crossref 10.65215/ysbyhc05 relation is-version-of 10.65215/r5bs2d54",
            "identical title and eight authors",
        ],
    ),
    # --- same work, no link: must stay a possible match until the user confirms ------------
    (
        "ambiguous_no_link",
        False,
        "10.2139/ssrn.5153505",
        "10.1016/j.chemolab.2025.105581",
        SAME,
        POSS,
        False,
        "An SSRN preprint and an Elsevier article with the same title and the same four authors: "
        "almost certainly one work, but no record links them, so only the user may merge them.",
        ["identical titles; same four authors", "no relation in either Crossref record"],
    ),
    (
        "ambiguous_no_link",
        False,
        "10.21203/rs.3.rs-3733479/v1",
        "10.1007/s10462-024-10808-0",
        SAME,
        POSS,
        False,
        "Research Square preprint and Springer article, same title and three authors, no link.",
        ["identical titles (case aside); same three authors", "no relation in either record"],
    ),
    (
        "ambiguous_no_link",
        False,
        "10.1561/2200000096",
        "10.1561/9781638281436",
        SAME,
        POSS,
        False,
        "The same survey published as a journal issue and as a book (now publishers): same title "
        "and eight authors, no link.",
        ["identical titles; same eight authors; no relation"],
    ),
    (
        "ambiguous_no_link",
        False,
        "10.65215/ysbyhc05",
        "10.65215/pc26a033",
        SAME,
        POSS,
        False,
        "Two posted copies of 'Attention Is All You Need' with the same eight authors and no "
        "link between these two deposits.",
        ["identical title and authors; no relation between these DOIs"],
    ),
    (
        "preprint_versions",
        False,
        "1706.03762",
        "10.65215/pc26a033",
        SAME,
        AUTO,
        False,
        "The arXiv paper and a posted copy with the same title and eight authors. No system of "
        "record links them, but the OpenAlex work for the arXiv paper lists the copy's DOI among "
        "its locations (a strong, non-decisive link). (Label corrected on evidence review: first "
        "drafted as an unlinked possible match before the OpenAlex location was checked.)",
        [
            "OpenAlex W2626778328 (doi 10.48550/arxiv.1706.03762) locations include "
            "https://doi.org/10.65215/pc26a033",
            "identical title; same eight authors",
        ],
    ),
    (
        "ambiguous_no_link",
        False,
        "hep-th/9711200",
        "10.1063/1.59653",
        SAME,
        POSS,
        False,
        "Maldacena's preprint and its 1999 AIP proceedings version: same title and author, no "
        "identifier link (the arXiv DOI is the ATMP one).",
        ["same title and author; no relation in the AIP record"],
    ),
    (
        "ambiguous_no_link",
        False,
        "hep-th/9711200",
        "10.4310/atmp.1998.v2.n2.a1",
        SAME,
        POSS,
        False,
        "Maldacena's preprint and its ATMP 1998 publication: same title and author, but neither "
        "record links the two (the arXiv DOI field names the IJTP printing).",
        [
            "same title and author",
            "arXiv <arxiv:doi> is 10.1023/A:1026654312961, not the ATMP DOI",
            "no relation in the ATMP Crossref record",
        ],
    ),
    (
        "ambiguous_no_link",
        False,
        "10.4310/atmp.1998.v2.n2.a1",
        "10.1023/a:1026654312961",
        SAME,
        POSS,
        False,
        "ATMP 1998 and the 1999 IJTP printing of the same paper: same title and author, no link.",
        ["same title and author; no relation in either record"],
    ),
    # --- different works with (near-)identical titles ---------------------------------------
    (
        "similar_title_different",
        True,
        "10.1109/access.2026.3665657",
        "10.4108/eetel.3466",
        DIFF,
        NONE,
        False,
        "Two different surveys both titled 'A Survey on Graph Neural Networks' (different authors "
        "and venues).",
        ["identical title", "no shared author (9 vs 1 authors)"],
    ),
    (
        "similar_title_different",
        True,
        "10.1002/minf.201501008",
        "10.31032/ijbpas/2023/12.10.1013",
        DIFF,
        NONE,
        False,
        "'Deep Learning in Drug Discovery' (Molecular Informatics 2016) and an unrelated 2023 "
        "article with the same title.",
        ["identical title; the 2023 record lists no authors; 7 years apart"],
    ),
    (
        "similar_title_different",
        True,
        "10.1016/b978-0-443-19413-9.00013-8",
        "10.1002/minf.201501008",
        DIFF,
        NONE,
        False,
        "A book chapter and a journal article both titled 'Deep learning in drug discovery', by "
        "different authors.",
        ["identical title; no shared author"],
    ),
    (
        "similar_title_different",
        True,
        "10.1007/978-3-031-84300-6_13",
        "10.65215/ysbyhc05",
        DIFF,
        NONE,
        False,
        "'Is Attention All You Need?' (a single-author chapter) is not 'Attention Is All You "
        "Need': same words, different work.",
        ["word-identical titles; no shared author"],
    ),
    (
        "similar_title_different",
        True,
        "10.1201/9781003561460-19",
        "10.65215/ysbyhc05",
        DIFF,
        NONE,
        False,
        "A two-author book chapter titled 'Attention Is All You Need' is not the Vaswani et al. "
        "paper.",
        ["identical title; no shared author"],
    ),
    (
        "similar_title_different",
        True,
        "10.1038/s43586-024-00294-7",
        "10.1038/s43586-024-00304-8",
        DIFF,
        NONE,
        False,
        "Nature Reviews Methods Primers article 'Graph neural networks' and a second record with "
        "the same title and no authors (a separate item).",
        ["identical title; the second record lists no authors"],
    ),
    (
        "similar_title_different",
        True,
        "10.1038/s43586-024-00294-7",
        "10.1007/978-981-16-6054-2_3",
        DIFF,
        NONE,
        False,
        "Two works titled 'Graph Neural Networks' by different authors (primer vs book chapter).",
        ["identical title; no shared author"],
    ),
    (
        "similar_title_different",
        True,
        "10.1021/acs.jcim.5c01019",
        "10.1021/acs.jcim.5c01019.s001",
        REL,
        NONE,
        False,
        "A JCIM article and its Supporting Information file: same title, but the supplement is a "
        "component, not the work.",
        ["Crossref .s001 type component, relation is-component-of the article; no authors"],
    ),
    # --- part series -------------------------------------------------------------------------
    (
        "part_series",
        True,
        "10.1016/0167-9473(95)00032-1",
        "10.1016/0167-9473(95)00033-x",
        DIFF,
        NONE,
        False,
        "'Neural networks and logistic regression: Part I' and 'Part II': same authors and issue, "
        "different papers.",
        ["titles differ only in the part number; same authors"],
    ),
    (
        "part_series",
        True,
        "10.3844/ajeassp.2017.457.472",
        "10.3844/ajeassp.2017.473.483",
        DIFF,
        NONE,
        False,
        "'Gears-Part I' and 'Gears-Part II': same authors, venue and date, different papers.",
        ["titles differ only in the part number; same three authors; consecutive pages"],
    ),
    # --- comments and replies ----------------------------------------------------------------
    (
        "comment_reply",
        True,
        "10.3390/insects17070712",
        "10.3390/insects17070713",
        REL,
        REL_O,
        True,
        "A comment and the authors' reply: related, never the same work.",
        ["Crossref relation is-reply-to between the two records"],
    ),
    (
        "comment_reply",
        True,
        "10.1075/lab.2.3.15vai",
        "10.1075/lab.2.3.01dab",
        REL,
        REL_O,
        True,
        "A commentary on a target article.",
        ["Crossref 10.1075/lab.2.3.15vai relation is-comment-on 10.1075/lab.2.3.01dab"],
    ),
    (
        "comment_reply",
        True,
        "10.1162/99608f92.66fb00a2",
        "10.1162/99608f92.95388fcb",
        REL,
        REL_O,
        True,
        "A Harvard Data Science Review commentary on a discussion article.",
        ["Crossref 10.1162/99608f92.66fb00a2 relation is-comment-on 10.1162/99608f92.95388fcb"],
    ),
    (
        "comment_reply",
        True,
        "10.21428/88de04a1.a9378969",
        "10.21428/88de04a1.12891b70",
        REL,
        REL_O,
        True,
        "A review/response published as a reply to a PubPub article.",
        ["Crossref 10.21428/88de04a1.a9378969 relation is-reply-to 10.21428/88de04a1.12891b70"],
    ),
    (
        "comment_reply",
        True,
        "10.21428/3b2160cd.c3935d14",
        "10.21428/3b2160cd.c34a55dc",
        REL,
        REL_O,
        True,
        "A reply to a PubPub article.",
        ["Crossref 10.21428/3b2160cd.c3935d14 relation is-reply-to 10.21428/3b2160cd.c34a55dc"],
    ),
    (
        "comment_reply",
        True,
        "10.7554/elife.89679.1.sa3",
        "10.7554/elife.89679.1",
        REL,
        NONE,
        False,
        "The authors' response to eLife's reviews: same title prefix, a peer-review document, "
        "never the paper. Crossref types it peer-review with is-review-of, which the matcher "
        "does not use as a link, so the correct outcome is to keep them apart.",
        ["Crossref .sa3 type peer-review, title 'Author Response: ...', relation is-review-of"],
    ),
    # --- corrections, retractions --------------------------------------------------------------
    (
        "correction_notice",
        True,
        "10.1088/1361-6595/ab245f",
        "10.1088/1361-6595/aaebdb",
        REL,
        REL_O,
        True,
        "An erratum and the article it corrects.",
        ["Crossref ab245f update-to (correction) 10.1088/1361-6595/aaebdb"],
    ),
    (
        "correction_notice",
        True,
        "10.1177/11795476221138199",
        "10.1177/11795476221126981",
        REL,
        REL_O,
        True,
        "A corrigendum and its article.",
        ["Crossref 11795476221138199 update-to (correction) 10.1177/11795476221126981"],
    ),
    (
        "correction_notice",
        True,
        "10.1371/journal.pone.0301214",
        "10.1371/journal.pone.0161231",
        REL,
        REL_O,
        True,
        "A PLOS ONE correction and its article.",
        ["Crossref pone.0301214 update-to (correction) 10.1371/journal.pone.0161231"],
    ),
    (
        "correction_notice",
        True,
        "10.1080/14688417.2024.2429234",
        "10.1080/14688417.2024.2416252",
        REL,
        REL_O,
        True,
        "A correction notice and its article.",
        ["Crossref 2429234 update-to (correction) 10.1080/14688417.2024.2416252"],
    ),
    (
        "correction_notice",
        True,
        "10.1111/psj.70162",
        "10.1111/psj.70147",
        REL,
        REL_O,
        True,
        "'Correction to \"Supply-Side Policy Feedback\"' and the article.",
        ["Crossref psj.70162 update-to (correction) 10.1111/psj.70147"],
    ),
    (
        "correction_notice",
        True,
        "10.1080/14767058.2026.2722700",
        "10.1080/14767058.2019.1659770",
        REL,
        REL_O,
        True,
        "A retraction statement and the retracted article.",
        ["Crossref 2026.2722700 update-to (retraction) 10.1080/14767058.2019.1659770"],
    ),
    (
        "correction_notice",
        True,
        "10.3844/ajeassp.2019.127",
        "10.3844/ajeassp.2017.457.472",
        REL,
        NONE,
        False,
        "'Corrigendum: Gears-Part I' and the article. Without an update-to link the matcher can "
        "only keep them apart (recognising the erratum needs the link).",
        ["title marker 'Corrigendum:'; shared first author"],
    ),
    (
        "correction_notice",
        True,
        "10.1093/bib/bbag239",
        "10.1093/bib/bbad467",
        REL,
        NONE,
        False,
        "'Correction to: Attention is all you need: utilizing attention in AI-enabled...' and the "
        "article; no update-to link, no authors on the notice: keep apart.",
        ["title marker 'Correction to:'; notice has no authors; no relation"],
    ),
    # --- related works that are not the same work -----------------------------------------
    (
        "related_extends",
        False,
        "1512.03385",
        "1603.05027",
        REL,
        NONE,
        False,
        "ResNet and 'Identity Mappings in Deep Residual Networks' (same authors, follow-up work).",
        ["different titles and arXiv IDs; the second extends the first"],
    ),
    (
        "related_extends",
        False,
        "10.1021/acs.jcim.5c01019",
        "10.1021/acs.jctc.4c00798",
        REL,
        NONE,
        False,
        "Two different GNN papers on molecular property prediction (quantum-embedded vs patch "
        "aggregation).",
        ["different titles, authors and journals"],
    ),
]


def match_dataset() -> dict[str, object]:
    cases = []
    for n, (cat, adv, a, b, rel, out, decisive, why, evidence) in enumerate(MATCH, start=1):
        cases.append(
            {
                "id": f"GM-B0-{n:03d}",
                "category": cat,
                "adversarial": adv,
                "a": a,
                "b": b,
                "expected": {
                    "relationship": rel,
                    "outcome": out,
                    "auto_merge_allowed": out == AUTO,
                    "user_confirmation_required": out == POSS,
                    "decisive_evidence": decisive,
                },
                "explanation": why,
                "evidence": evidence,
                "provenance": "recorded",
                "labels": {**LABELS, "guideline": "g-match-guidelines-v0.1"},
            }
        )
    return {
        "benchmark": "G-MATCH",
        "split": "B0",
        "version": "b0-v0.1",
        "description": "Development split (B0) of G-MATCH: real record pairs from arXiv, "
        "Crossref, bioRxiv/medRxiv (and Semantic Scholar where recorded), chosen to cover each "
        "category of EVALUATION_FRAMEWORK §2. Labels are AI-proposed from the evidence quoted "
        "per case and await team review; they are not gold and support no release claim.",
        "recordings": RECORDINGS,
        "match_cases": cases,
    }


# --- G-LATEST-DATES ---------------------------------------------------------------------------
# Expected values follow the guideline rules applied to the recorded records (quoted in
# ``evidence``); where policy and truth could differ, ``explanation`` says which is labelled.
QM, DL = ["q-bio.QM"], ["cs.DL"]
NOV11 = ("2026-11-11", "2026-11-11")
VERIFIED, UNCERTAIN = "verified", "uncertain"


def _e(
    date: str | None,
    basis: str | None,
    confidence: str,
    kind: str | None = None,
    candidate: str | None = None,
    window: object = None,
    release: str | None = None,
) -> dict[str, object]:
    out: dict[str, object] = {"first_public_date": date, "basis": basis, "confidence": confidence}
    for key, value in (
        ("first_public_kind", kind),
        ("candidate_public_date", candidate),
        ("window", list(window) if isinstance(window, tuple) else window),
        ("release_type", release),
    ):
        if value is not None:
            out[key] = value
    return out


ANNOUNCED_NOTE = (
    "arXiv RSS {feed} feed of Wed 2026-11-11 (pubDate 00:00 -0500) lists {id}v1 "
    "with announce_type new"
)
# (category, identifiers, capture_feeds, expected, explanation, evidence)
DATES: list[tuple[str, list[str], list[str], dict[str, object], str, list[str]]] = [
    # --- arXiv: announced new submissions (captured) ------------------------------------
    *[
        (
            "arxiv_announced",
            [i],
            feeds,
            _e(
                "2026-11-11",
                "announced",
                VERIFIED,
                "preprint",
                window=NOV11,
                release="new_preprint",
            ),
            f"A new arXiv submission (submitted {sub}) first announced on 2026-11-11 in its "
            "primary category; the captured announcement is the first public appearance, so the "
            "work is new research for that day.",
            [
                ANNOUNCED_NOTE.format(feed=feeds[0], id=i),
                f"arXiv API {i}: published {sub} (v1), primary category {feeds[0]}",
            ],
        )
        for i, feeds, sub in [
            ("2611.13190", QM, "2026-11-09T20:10:37Z"),
            ("2611.13398", QM, "2026-11-10T00:20:01Z"),
            ("2611.14184", QM, "2026-11-10T15:06:38Z"),
            ("2611.13216", DL, "2026-11-09T20:38:40Z"),
        ]
    ],
    # --- arXiv: no announcement captured -> submission only -----------------------------
    *[
        (
            "arxiv_submission_only",
            [i],
            [],
            _e(day, "submission_only", VERIFIED, "preprint", window=NOV11, release="none"),
            "The same arXiv paper without capturing its announcement: only the v1 submission "
            "time is known, which is stated as a submission (verified as such), never as the "
            "release date. Nothing places the work in the 2026-11-11 window (the true "
            "announcement day), which is the honest result without the feed.",
            [f"arXiv API {i}: published {sub} (v1); no feed captured; no aggregator record"],
        )
        for i, day, sub in [
            ("2611.13190", "2026-11-09", "2026-11-09T20:10:37Z"),
            ("2611.13216", "2026-11-09", "2026-11-09T20:38:40Z"),
        ]
    ],
    # --- arXiv: cross-listings are not announcements of the work ------------------------
    *[
        (
            "arxiv_cross_listing",
            [i],
            QM,
            _e(day, "submission_only", VERIFIED, "preprint", window=NOV11, release="none"),
            f"Listed in the q-bio.QM feed as a cross-listing ({kind}) from primary category "
            f"{prim}. A cross-listing is not an announcement of the work, so the first public "
            "date stays the v1 submission (submission only) and the feed entry places nothing "
            "in the window.",
            [
                f"arXiv RSS q-bio.QM 2026-11-11: {i}v{v} announce_type {kind}",
                f"arXiv API {i}: published {sub} (v1), primary {prim}",
            ],
        )
        for i, day, sub, prim, kind, v in [
            ("2611.13277", "2026-11-09", "2026-11-09T21:42:14Z", "eess.SY", "cross", 1),
            ("2611.13692", "2026-11-10", "2026-11-10T07:39:57Z", "q-bio.NC", "cross", 1),
            ("2611.13876", "2026-11-10", "2026-11-10T10:36:01Z", "cs.ET", "cross", 1),
            ("2611.14511", "2026-11-10", "2026-11-10T18:56:32Z", "cs.LG", "cross", 1),
            ("2508.02061", "2025-08-04", "2025-08-04T05:00:15Z", "q-bio.GN", "replace-cross", 3),
            ("2512.17129", "2025-12-18", "2025-12-18T23:50:42Z", "cs.LG", "replace-cross", 3),
            ("2611.01666", "2026-11-01", "2026-11-01T07:21:43Z", "cs.LG", "replace-cross", 3),
        ]
    ],
    # --- arXiv: revisions are not new works -----------------------------------------------
    (
        "arxiv_revision",
        ["2609.21394"],
        QM,
        _e(
            "2026-09-18",
            "submission_only",
            VERIFIED,
            "preprint",
            window=NOV11,
            release="revised_version",
        ),
        "Version 2 of a September paper announced on 2026-11-11 (replace). The work's first "
        "public date stays v1's (submission only: v1's announcement was not captured); in the "
        "window it is a revised version, never a new preprint.",
        [
            "arXiv RSS q-bio.QM 2026-11-11: 2609.21394v2 announce_type replace",
            "arXiv API: published 2026-09-18T07:06:29Z (v1), updated 2026-11-10T07:49:47Z (v2)",
        ],
    ),
    (
        "arxiv_revision",
        ["2604.22997"],
        QM,
        _e(
            None,
            None,
            "single_source",
            candidate="2026-04-24",
            window=NOV11,
            release="revised_version",
        ),
        "Version 2 of an April paper announced on 2026-11-11. OpenAlex reports a publication "
        "date (2026-04-24), a public-availability claim of unknown upstream, so the "
        "submission-only fallback does not apply: the date is single-source and shown only as "
        "unconfirmed. The primary v1 submission still shows the paper existed before the window, "
        "so it is a revised version, not new research.",
        [
            "arXiv RSS q-bio.QM 2026-11-11: 2604.22997v2 announce_type replace",
            "arXiv API: published 2026-04-24T20:31:36Z (v1), updated 2026-11-10T18:10:49Z",
            "OpenAlex doi:10.48550/arxiv.2604.22997 publication_date 2026-04-24",
        ],
    ),
    # --- preprint servers ---------------------------------------------------------------------
    *[
        (
            "server_posted",
            [doi],
            [],
            _e(posted, "posted", VERIFIED, "preprint"),
            f"{server} preprint: the server's v1 posting date is the first public appearance "
            f"(the journal version, {pub}, is later). {extra}",
            [f"{server} API details {doi}: v1 date {posted}, published {pub}", *more],
        )
        for doi, server, posted, pub, extra, more in [
            (
                "10.1101/2022.10.22.513336",
                "bioRxiv",
                "2022-10-22",
                "10.7554/elife.87434",
                "OpenAlex's 2023-05-05 (= the eLife record's created date) disagrees and must not "
                "move the date.",
                [
                    "OpenAlex publication_date 2023-05-05",
                    "Crossref eLife 87434 published-online 2024-06-03",
                ],
            ),
            (
                "10.1101/2023.12.14.23299828",
                "medRxiv",
                "2023-12-15",
                "10.1001/jamapediatrics.2024.1379",
                "The DOI suffix suggests 2023-12-14; the posting date decides. OpenAlex's "
                "2024-06-03 is the journal's date.",
                ["OpenAlex publication_date 2024-06-03"],
            ),
            (
                "10.1101/2023.07.10.548412",
                "bioRxiv",
                "2023-07-11",
                "10.7554/elife.89017.3",
                "The DOI suffix suggests 2023-07-10; the posting date decides.",
                [],
            ),
            (
                "10.1101/2023.08.14.553247",
                "bioRxiv",
                "2023-08-16",
                "10.7554/elife.91924.3",
                "The DOI suffix suggests 2023-08-14; the posting date decides.",
                [],
            ),
        ]
    ],
    # --- journal versions of older preprints: the preprint's date, never the journal's ---
    *[
        (
            "journal_of_older_preprint",
            [journal],
            [],
            _e(
                posted,
                "posted",
                VERIFIED,
                "preprint",
                window=(online, online),
                release="published_version_of_preprint",
            ),
            f"Added by its journal DOI. The journal record links the {server} preprint "
            f"(has-preprint), posted {posted}; the work's first public date is the preprint's, "
            f"and the journal version (online {online}) is a published version of an earlier "
            "preprint, never new research.",
            [
                f"Crossref {journal}: published-online {online}; relation has-preprint {pre}",
                f"{server} {pre}: v1 posted {posted}",
            ],
        )
        for journal, pre, server, posted, online in [
            (
                "10.7554/elife.92909",
                "10.1101/2023.10.03.560658",
                "bioRxiv API",
                "2023-10-05",
                "2024-06-03",
            ),
            (
                "10.1093/plphys/kiae255",
                "10.1101/2021.10.22.465218",
                "bioRxiv API",
                "2021-10-24",
                "2024-06-03",
            ),
            (
                "10.1038/s42003-024-06342-y",
                "10.1101/2023.07.27.550891",
                "bioRxiv API",
                "2023-07-30",
                "2024-06-03",
            ),
            (
                "10.1038/s41598-024-63226-1",
                "10.1101/2021.12.07.471480",
                "bioRxiv API",
                "2021-12-09",
                "2024-06-03",
            ),
            (
                "10.1371/journal.pbio.3002664",
                "10.1101/2023.10.02.560470",
                "bioRxiv API",
                "2023-10-02",
                "2024-06-03",
            ),
            (
                "10.1021/acs.jcim.6c01012",
                "10.26434/chemrxiv.15006367/v1",
                "ChemRxiv (Crossref posted-content)",
                "2026-07-21",
                "2026-09-04",
            ),
        ]
    ],
    (
        "journal_of_older_preprint",
        ["10.1001/jamapediatrics.2024.1379"],
        [],
        _e("2023-12-15", "posted", VERIFIED, "preprint"),
        "JAMA Pediatrics article added by DOI; its medRxiv preprint (posted 2023-12-15) is the "
        "first public appearance, not the journal's August 2024 issue.",
        [
            "Crossref: published-print 2024-08-01, created 2024-06-03; has-preprint "
            "10.1101/2023.12.14.23299828",
            "medRxiv API: v1 2023-12-15",
        ],
    ),
    # --- journal articles without a preprint --------------------------------------------------
    (
        "journal_only",
        ["10.1080/14767058.2019.1659770"],
        [],
        _e(
            "2019-09-04",
            "published_online",
            VERIFIED,
            "published",
            window=("2019-09-04", "2019-09-04"),
            release="new_publication",
        ),
        "A journal article with no known preprint: first public online 2019-09-04 (the print "
        "issue followed in 2021). OpenAlex's 2019-08-23 equals the Crossref created date "
        "(metadata), disagrees with the system of record and must not move the date.",
        [
            "Crossref: published-online 2019-09-04, published-print 2021-07-03, created 2019-08-23",
            "OpenAlex publication_date 2019-08-23",
        ],
    ),
    (
        "journal_only",
        ["10.1111/psj.70147"],
        [],
        _e(
            "2026-08-07",
            "published_online",
            VERIFIED,
            "published",
            window=("2026-08-07", "2026-08-07"),
            release="new_publication",
        ),
        "Journal article online 2026-08-07; the August 2026 issue is month-only and OpenAlex's "
        "2026-08-01 is a month value (day 01).",
        [
            "Crossref: published-online 2026-08-07, published-print 2026-08, issued 2026-08",
            "OpenAlex publication_date 2026-08-01",
        ],
    ),
    (
        "journal_only",
        ["10.31032/ijbpas/2023/12.10.1013"],
        [],
        _e("2023-10-15", "published_online", VERIFIED, "published"),
        "Journal article online 2023-10-15; the earlier created date (2023-10-12) is metadata.",
        ["Crossref: published-online 2023-10-15, created 2023-10-12"],
    ),
    (
        "journal_only",
        ["10.1371/journal.pone.0301214"],
        [],
        _e(
            "2024-03-21",
            "published_online",
            VERIFIED,
            window=("2024-03-21", "2024-03-21"),
            release="correction_notice",
        ),
        "A PLOS ONE correction notice published 2024-03-21: in its window it is a correction "
        "notice, never new research.",
        [
            "Crossref: published-online 2024-03-21; update-to correction of "
            "10.1371/journal.pone.0161231"
        ],
    ),
    # --- metadata dates are not public availability --------------------------------------------
    (
        "metadata_vs_public",
        ["10.1371/journal.pone.0161231"],
        [],
        _e(
            "2016-08-22",
            "published_online",
            VERIFIED,
            "published",
            window=("2026-10-15", "2026-10-15"),
            release="none",
        ),
        "A 2016 article whose Crossref record was re-indexed on 2026-10-15: indexing is "
        "metadata, so nothing places the work in that day's window.",
        ["Crossref: published-online 2016-08-22, indexed 2026-10-15"],
    ),
    (
        "metadata_vs_public",
        ["10.1021/acs.jcim.5c01019"],
        [],
        _e(
            "2025-07-26",
            "published_online",
            VERIFIED,
            "published",
            window=("2026-11-10", "2026-11-10"),
            release="none",
        ),
        "Online 2025-07-26; re-indexed 2026-11-10 (metadata only).",
        ["Crossref: published-online 2025-07-26, published-print 2025-08-11, indexed 2026-11-10"],
    ),
    (
        "metadata_vs_public",
        ["10.31032/ijbpas/2023/12.10.1013"],
        [],
        _e(
            "2023-10-15",
            "published_online",
            VERIFIED,
            "published",
            window=("2023-10-12", "2023-10-12"),
            release="none",
        ),
        "The Crossref record was created 2023-10-12, three days before the article went "
        "online: creation is not public availability.",
        ["Crossref: created 2023-10-12, published-online 2023-10-15"],
    ),
    # --- nominal issue dates vs online publication ----------------------------------------------
    (
        "conflicting",
        ["10.1088/1361-6595/aaebdb"],
        [],
        _e("2018-11-19", "published_online", VERIFIED, "published"),
        "Crossref gives published-print 2018-11-01 and published-online 2018-11-19. The print "
        "date is the nominal date of the November 2018 issue (day 01), not a day the article "
        "was public: an article cannot appear in an issue before it is online. The first "
        "public appearance is the online date.",
        ["Crossref: published-print 2018-11-01, published-online 2018-11-19, created 2018-10-26"],
    ),
    (
        "conflicting",
        ["10.1093/bib/bbag239"],
        [],
        _e("2026-04-30", "published_online", VERIFIED, "published"),
        "Crossref gives published-print 2026-03-01 (the nominal March issue) but the notice "
        "went online on 2026-04-30; the online date is the first public appearance.",
        ["Crossref: published-print 2026-03-01, published-online 2026-04-30, created 2026-04-30"],
    ),
    (
        "insufficient_evidence",
        ["10.3844/ajeassp.2017.457.472"],
        [],
        _e(None, None, UNCERTAIN),
        "Only a nominal issue date (published-print 2017-02-01, day 01) and a record created "
        "2017-07-18: no day of public availability is known, so the date is uncertain.",
        ["Crossref: published-print 2017-02-01, issued 2017-02-01, created 2017-07-18"],
    ),
    # --- reduced precision --------------------------------------------------------------------
    (
        "reduced_precision",
        ["10.1016/0167-9473(95)00032-1"],
        [],
        _e(None, None, UNCERTAIN),
        "Month-only issue date (June 1996); OpenAlex's 1996-06-01 is the same month value.",
        ["Crossref: published-print 1996-06, issued 1996-06", "OpenAlex 1996-06-01"],
    ),
    (
        "reduced_precision",
        ["10.1063/1.59653"],
        [],
        _e(None, None, UNCERTAIN),
        "Year-only proceedings date (1999). OpenAlex reports 1999-01-01: a year value with "
        "reduced precision, never a day.",
        ["Crossref: published-print 1999, issued 1999", "OpenAlex publication_date 1999-01-01"],
    ),
    (
        "reduced_precision",
        ["10.4310/atmp.1998.v2.n2.a1"],
        [],
        _e(None, None, UNCERTAIN),
        "Year-only journal date (1998); OpenAlex 1998-01-01 is a year value.",
        ["Crossref: published-print 1998", "OpenAlex publication_date 1998-01-01"],
    ),
    (
        "reduced_precision",
        ["10.1023/a:1026654312961"],
        [],
        _e(None, None, UNCERTAIN),
        "Month-only issue date (April 1999); OpenAlex 1999-04-01 is a month value. (The arXiv "
        "preprint of this work is not linked from this record, so it is not known here.)",
        ["Crossref: published-print 1999-04, issued 1999-04", "OpenAlex 1999-04-01"],
    ),
    # --- newly indexed, not newly released ---------------------------------------------------
    (
        "newly_indexed_older",
        ["1706.03762"],
        [],
        _e(
            None,
            None,
            "source_agreement",
            candidate="2017-06-12",
            window="run_day",
            release="newly_indexed_older",
        ),
        "A 2017 arXiv paper added today: newly indexed, never new research. OpenAlex and "
        "Semantic Scholar both report 2017-06-12 (a public claim of unknown upstream), so the "
        "date is source agreement, shown as unconfirmed.",
        [
            "arXiv API: published 2017-06-12T17:57:34Z (v1)",
            "OpenAlex publication_date 2017-06-12",
            "Semantic Scholar publicationDate 2017-06-12",
        ],
    ),
    (
        "newly_indexed_older",
        ["1512.03385"],
        [],
        _e(
            None,
            None,
            "source_agreement",
            candidate="2015-12-10",
            window="run_day",
            release="newly_indexed_older",
        ),
        "A 2015 arXiv paper added today: newly indexed. OpenAlex and S2 agree on 2015-12-10.",
        [
            "arXiv API: published 2015-12-10T19:51:55Z (v1)",
            "OpenAlex 2015-12-10",
            "Semantic Scholar 2015-12-10",
        ],
    ),
    (
        "insufficient_evidence",
        ["hep-th/9711200"],
        [],
        _e(None, None, UNCERTAIN, window="run_day", release="newly_indexed_older"),
        "Maldacena 1997, added today. The arXiv record's DOI brings in the IJTP printing, whose "
        "only dates are month-only (April 1999): a public claim exists but no day-precision "
        "public date, so the submission-only fallback does not apply and the date is uncertain. "
        "The 1997 submission shows the work is old: newly indexed, never new research.",
        [
            "arXiv API: published 1997-11-27T23:53:13Z, doi 10.1023/A:1026654312961",
            "Crossref 10.1023/a:1026654312961: issued 1999-04",
        ],
    ),
]


def dates_dataset() -> dict[str, object]:
    cases = []
    for n, (cat, ids, feeds, expected, why, evidence) in enumerate(DATES, start=1):
        cases.append(
            {
                "id": f"GD-B0-{n:03d}",
                "category": cat,
                "identifiers": ids,
                "capture_feeds": feeds,
                "expected": expected,
                "explanation": why,
                "evidence": evidence,
                "provenance": "recorded",
                "labels": {**LABELS, "guideline": "g-latest-dates-guidelines-v0.1"},
            }
        )
    return {
        "benchmark": "G-LATEST-DATES",
        "split": "B0",
        "version": "b0-v0.1",
        "description": "Development split (B0) of G-LATEST-DATES: real recorded records from "
        "arXiv (API and the 2026-11-11 announcement feeds), bioRxiv/medRxiv, Crossref and, "
        "where recorded, OpenAlex and Semantic Scholar. Labels are AI-proposed from the "
        "evidence quoted per case and await team review; they are not gold and support no "
        "release claim.",
        "recordings": RECORDINGS,
        "date_cases": cases,
    }


if __name__ == "__main__":
    for name, data, n in (
        ("g_match", match_dataset(), len(MATCH)),
        ("g_latest_dates", dates_dataset(), len(DATES)),
    ):
        out = HERE / name / "b0.json"
        out.write_text(json.dumps(data, indent=1) + "\n")
        print(f"{out}: {n} cases")
