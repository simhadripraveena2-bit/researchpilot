"""Release-type classifier (ARCHITECTURE §4.8.4): why a work appears in a date window.

Pure function of a work's stored date events, its manifestations and a window. It reuses the
Date Resolver for confidence and first public appearance, and never changes stored data.

Rules (in this order):

* **Correction notice** - every manifestation is a notice (correction, retraction,
  expression of concern; Crossref ``update-to``) and one of its public events is in the
  window. A notice is never research of its own.
* With a **verified or corroborated** first public appearance (FPA):
  * FPA in the window on a preprint -> **new preprint** (``submission_only`` labelled);
  * FPA in the window on a published version -> **new publication**, only if no earlier or
    other preprint version is known; otherwise **date uncertain** (an earlier version exists
    whose public date is not confirmed);
  * FPA before the window, a primary published-version event (online, issue, issued) in the
    window and the FPA on a preprint -> **published version of an earlier preprint** (never
    new research; the preprint date is reported);
  * FPA before the window, a primary revision event (v2+) in the window -> **revised version**;
  * FPA before the window, an index event (OpenAlex ``created_date`` or our first-seen) in the
    window -> **older paper newly indexed**.
* **Not verified** (source agreement, single source, conflicting, uncertain): nothing is ever
  promoted. A revision or index event in the window counts only when a primary event shows the
  paper existed before the window (revised version / newly indexed); any other public, revision,
  publication or index event in the window -> **date uncertain**.
* Metadata dates never place a paper; dates more than a day after ``as_of`` are ignored;
  month/year values never fall in windows of 31 days or less (``windows.place``).

Result ``None``: nothing about the work happened in the window.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from researchpilot.domain.enums import (
    NOTICE_TYPES,
    DateConfidence,
    DateEvent,
    DatePrecision,
    FirstPublicBasis,
    ManifestationKind,
    PeerReviewLabel,
    PublicationType,
    ReleaseType,
)
from researchpilot.domain.windows import Window, place
from researchpilot.services.dates.resolver import (
    FUTURE_TOLERANCE,
    PUBLIC_EVENTS,
    DateClaim,
    DateResolution,
    resolve,
)

CONFIRMED = frozenset({DateConfidence.VERIFIED, DateConfidence.CORROBORATED})
PUBLISHED_EVENTS = frozenset(
    {DateEvent.PUBLISHED_ONLINE, DateEvent.ISSUE_PUBLISHED, DateEvent.ISSUED}
)
VERSION_EVENTS = frozenset(
    {DateEvent.VERSION_SUBMITTED, DateEvent.VERSION_ANNOUNCED, DateEvent.VERSION_POSTED}
)
INDEX_EVENTS = frozenset({DateEvent.INDEX_CREATED, DateEvent.FIRST_SEEN_BY_RESEARCHPILOT})
EXISTENCE_EVENTS = frozenset(PUBLIC_EVENTS) | {DateEvent.PREPRINT_SUBMITTED}
DAY_OR_BETTER = frozenset({DatePrecision.TIMESTAMP, DatePrecision.DAY})
# Order among simultaneous candidates (tie-break only).
_EVENT_ORDER = {
    e: i
    for i, e in enumerate(
        [
            DateEvent.PREPRINT_ANNOUNCED,
            DateEvent.PREPRINT_POSTED,
            DateEvent.PUBLISHED_ONLINE,
            DateEvent.ISSUE_PUBLISHED,
            DateEvent.ISSUED,
            DateEvent.VERSION_ANNOUNCED,
            DateEvent.VERSION_POSTED,
            DateEvent.VERSION_SUBMITTED,
            DateEvent.PREPRINT_SUBMITTED,
            DateEvent.REPORTED_PUBLICATION_DATE,
            DateEvent.INDEX_CREATED,
            DateEvent.FIRST_SEEN_BY_RESEARCHPILOT,
        ]
    )
}


@dataclass(frozen=True)
class ManifestationInfo:
    id: uuid.UUID
    kind: ManifestationKind
    publication_type: PublicationType
    server_or_venue: str
    peer_review_label: PeerReviewLabel


@dataclass(frozen=True)
class WorkDates:
    paper_id: uuid.UUID
    claims: tuple[DateClaim, ...]
    manifestations: Mapping[uuid.UUID, ManifestationInfo]
    # Sources whose records were consulted for this work (for "no earlier preprint found in").
    checked_sources: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Release:
    release_type: ReleaseType
    event: DateClaim  # the event that placed the work in the window
    manifestation: ManifestationInfo
    boundary_day: bool
    confidence: DateConfidence
    basis: FirstPublicBasis | None
    first_public: DateClaim | None
    reason: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_new_research(self) -> bool:
        return self.release_type in (ReleaseType.NEW_PREPRINT, ReleaseType.NEW_PUBLICATION)


def classify(work: WorkDates, window: Window, as_of: datetime) -> Release | None:
    return _Classifier(work, window, as_of).run()


class _Classifier:
    def __init__(self, work: WorkDates, window: Window, as_of: datetime) -> None:
        self.work = work
        self.window = window
        self.claims = [c for c in work.claims if c.value <= as_of + FUTURE_TOLERANCE]
        self.resolution: DateResolution = resolve(list(work.claims), as_of)
        self.primary = [c for c in self.claims if c.is_primary and c.precision in DAY_OR_BETTER]
        self.revisions = self.inside(
            c for c in self.primary if c.event in VERSION_EVENTS and (c.version or 0) >= 2
        )
        self.indexed = self.inside(c for c in self.claims if c.event in INDEX_EVENTS)

    # --- helpers -----------------------------------------------------------------------

    def inside(self, candidates: Iterable[DateClaim]) -> list[DateClaim]:
        return sorted(
            (c for c in candidates if place(c.value, c.precision, self.window).inside),
            key=lambda c: (c.value, _EVENT_ORDER.get(c.event, 99)),
        )

    def before(self, c: DateClaim) -> bool:
        return place(c.value, c.precision, self.window).relation == "before"

    def make(self, kind: ReleaseType, event: DateClaim, reason: str, *notes: str) -> Release:
        return Release(
            release_type=kind,
            event=event,
            manifestation=self.work.manifestations[event.manifestation_id],
            boundary_day=place(event.value, event.precision, self.window).boundary_day,
            confidence=self.resolution.confidence,
            basis=self.resolution.basis,
            first_public=self.resolution.first_public,
            reason=reason,
            notes=tuple(notes),
        )

    # --- rules -------------------------------------------------------------------------

    def run(self) -> Release | None:
        manifestations = self.work.manifestations
        if manifestations and all(
            m.publication_type in NOTICE_TYPES for m in manifestations.values()
        ):
            return self.notice()
        fpa = self.resolution.first_public
        if self.resolution.confidence in CONFIRMED and fpa is not None:
            return self.confirmed(fpa)
        return self.unconfirmed()

    def notice(self) -> Release | None:
        public = self.inside(
            c
            for c in self.claims
            if _is_public(c) or c.event is DateEvent.REPORTED_PUBLICATION_DATE
        )
        if not public:
            return None
        kind = self.work.manifestations[public[0].manifestation_id].publication_type
        return self.make(
            ReleaseType.CORRECTION_NOTICE,
            public[0],
            f"a {kind.value.replace('_', ' ')} notice about another work; not new research",
        )

    def confirmed(self, fpa: DateClaim) -> Release | None:
        work = self.work
        fpa_m = work.manifestations[fpa.manifestation_id]
        placement = place(fpa.value, fpa.precision, self.window)
        if placement.inside:
            if fpa_m.kind is ManifestationKind.PREPRINT:
                notes = (
                    ("submission time used; public announcement not captured",)
                    if (self.resolution.basis is FirstPublicBasis.SUBMISSION_ONLY)
                    else ()
                )
                return self.make(
                    ReleaseType.NEW_PREPRINT,
                    fpa,
                    "first public appearance of the work, as a preprint",
                    *notes,
                )
            earlier = [
                c
                for c in self.claims
                if c.manifestation_id != fpa.manifestation_id
                and c.value < fpa.value
                and (c.event in EXISTENCE_EVENTS or c.event is DateEvent.REPORTED_PUBLICATION_DATE)
            ]
            other_preprints = [
                m
                for m in work.manifestations.values()
                if m.kind is ManifestationKind.PREPRINT and m.id != fpa.manifestation_id
            ]
            if earlier or other_preprints:
                return self.make(
                    ReleaseType.DATE_UNCERTAIN,
                    fpa,
                    "an earlier version of this work is known, but its public date is not "
                    "confirmed; it is not presented as new research",
                )
            searched = ", ".join(sorted(work.checked_sources)) or "the linked records"
            return self.make(
                ReleaseType.NEW_PUBLICATION,
                fpa,
                "first public appearance of the work, as a published version",
                f"No earlier preprint found in: {searched}",
            )
        if placement.relation == "after":
            return None
        # First public appearance before the window: never new research.
        if fpa_m.kind is ManifestationKind.PREPRINT:
            published = self.inside(
                c
                for c in self.primary
                if c.event in PUBLISHED_EVENTS
                and work.manifestations[c.manifestation_id].kind is not ManifestationKind.PREPRINT
            )
            if published:
                return self.make(
                    ReleaseType.PUBLISHED_VERSION_OF_PREPRINT,
                    published[0],
                    "a published version of a preprint that was public before the window",
                    f"Preprint public since {fpa.value.date().isoformat()}",
                )
        if self.revisions:
            return self.make(
                ReleaseType.REVISED_VERSION,
                self.revisions[0],
                "a new version of a paper that was public before the window",
            )
        if self.indexed:
            return self.make(
                ReleaseType.NEWLY_INDEXED_OLDER,
                self.indexed[0],
                "first indexed in the window; public before it",
                _index_note(self.indexed[0]),
            )
        return None

    def unconfirmed(self) -> Release | None:
        """Never promoted. Older status needs primary evidence from before the window."""
        confidence = self.resolution.confidence.value
        # Primary evidence of existence before the window; a month/year value counts when its
        # whole period is before the window (e.g. Crossref "2016-06" for a 2026 window).
        existed_before = any(
            c.is_primary and c.event in EXISTENCE_EVENTS and self.before(c) for c in self.claims
        )
        if self.revisions and existed_before:
            return self.make(
                ReleaseType.REVISED_VERSION,
                self.revisions[0],
                "a new version of a paper that existed before the window "
                f"(first public date {confidence})",
            )
        public_inside = self.inside(c for c in self.claims if _is_public(c))
        if self.indexed and existed_before and not public_inside:
            return self.make(
                ReleaseType.NEWLY_INDEXED_OLDER,
                self.indexed[0],
                "first indexed in the window; the paper existed earlier "
                f"(first public date {confidence})",
                _index_note(self.indexed[0]),
            )
        # Month/year values count only when entirely inside a window longer than 31 days
        # (``place``); they can never be more than "date uncertain".
        evidence = self.inside(
            c
            for c in self.claims
            if _is_public(c)
            or c.event is DateEvent.REPORTED_PUBLICATION_DATE
            or (
                c.precision in DAY_OR_BETTER
                and (
                    c.event in VERSION_EVENTS
                    or c.event in INDEX_EVENTS
                    or (c.event is DateEvent.PREPRINT_SUBMITTED and c.is_primary)
                )
            )
        )
        if evidence:
            return self.make(
                ReleaseType.DATE_UNCERTAIN,
                evidence[0],
                f"date {confidence}: {self.resolution.reason}",
            )
        return None


def _is_public(c: DateClaim) -> bool:
    return c.event in PUBLIC_EVENTS and c.version in (None, 1)


def _index_note(c: DateClaim) -> str:
    if c.event is DateEvent.FIRST_SEEN_BY_RESEARCHPILOT:
        return "based on when ResearchPilot first saw it (not when the source indexed it)"
    return f"index date reported by {c.reporting_source.value}"


__all__ = ["ManifestationInfo", "Release", "WorkDates", "classify"]
