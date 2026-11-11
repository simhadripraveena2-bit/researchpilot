"""Date Resolver (ARCHITECTURE §4.8.3-4.8.4, decision D28 revised).

Pure function of a work's date events (all manifestations). It never overstates:

* ``verified`` - a **primary** public-availability event (from the manifestation's system
  of record) at day/timestamp precision, with no primary event of the same kind disagreeing
  by more than 2 days. For arXiv works without a captured announcement, the v1 submission
  timestamp is used with the labelled basis ``submission_only`` (verified *as a submission*,
  never presented as the release date).
* ``corroborated`` - no primary event, but two public-availability claims with known,
  different upstream sources agree within +-1 day.
* ``source_agreement`` - several reporting sources agree (+-1 day) but independence cannot be
  shown (unknown or shared upstream).
* ``single_source`` - exactly one secondary claim (or claims from a single reporting source).
* ``conflicting`` - primary events of one kind disagree by > 2 days, or secondary claims
  disagree (> 1 day apart) with no primary event.
* ``uncertain`` - month/year precision only, future dates only, or no claim.

A secondary claim that disagrees with every primary public event by more than 2 days is
flagged ``disagrees_with_primary``; the primary date stands. Dates more than one day after
retrieval are flagged ``future_date`` and ignored.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from researchpilot.domain.enums import (
    DateConfidence,
    DateEvent,
    DatePrecision,
    FirstPublicBasis,
    ReportingSource,
    UpstreamSource,
)

PRIMARY_CONFLICT = timedelta(days=2)
AGREEMENT = timedelta(days=1)
FUTURE_TOLERANCE = timedelta(days=1)

# Events that can be a work's first public appearance, and the basis each one gives.
PUBLIC_EVENTS: dict[DateEvent, FirstPublicBasis] = {
    DateEvent.PREPRINT_ANNOUNCED: FirstPublicBasis.ANNOUNCED,
    DateEvent.PREPRINT_POSTED: FirstPublicBasis.POSTED,
    DateEvent.PUBLISHED_ONLINE: FirstPublicBasis.PUBLISHED_ONLINE,
    DateEvent.ISSUE_PUBLISHED: FirstPublicBasis.ISSUE,
    DateEvent.ISSUED: FirstPublicBasis.ISSUED,
}
DAY_OR_BETTER = frozenset({DatePrecision.TIMESTAMP, DatePrecision.DAY})

FLAG_FUTURE = "future_date"
FLAG_DISAGREES = "disagrees_with_primary"


@dataclass(frozen=True)
class DateClaim:
    id: uuid.UUID
    manifestation_id: uuid.UUID
    event: DateEvent
    value: datetime
    precision: DatePrecision
    is_primary: bool
    reporting_source: ReportingSource
    upstream_source: UpstreamSource = UpstreamSource.UNKNOWN
    version: int | None = None


@dataclass(frozen=True)
class DateResolution:
    confidence: DateConfidence
    first_public: DateClaim | None = None  # set only for verified / corroborated
    basis: FirstPublicBasis | None = None
    candidate_public_date: date | None = None  # best unconfirmed date otherwise
    reason: str = ""
    flags: dict[uuid.UUID, tuple[str, ...]] = field(default_factory=dict)


def resolve(claims: list[DateClaim], retrieved_at: datetime) -> DateResolution:
    flags: dict[uuid.UUID, list[str]] = defaultdict(list)
    usable: list[DateClaim] = []
    for claim in claims:
        if claim.value > retrieved_at + FUTURE_TOLERANCE:
            flags[claim.id].append(FLAG_FUTURE)
        elif claim.precision in DAY_OR_BETTER:
            usable.append(claim)

    primary_public = [c for c in usable if c.is_primary and _is_public(c)]
    submission = _submission_only_fallback(usable)
    secondary = [c for c in usable if not c.is_primary and _counts_as_secondary(c)]

    def done(result: DateResolution) -> DateResolution:
        return DateResolution(
            **{**result.__dict__, "flags": {k: tuple(v) for k, v in flags.items() if v}}
        )

    if primary_public or submission:
        if primary_public:
            for claim in secondary:
                if all(abs(claim.value - p.value) > PRIMARY_CONFLICT for p in primary_public):
                    flags[claim.id].append(FLAG_DISAGREES)
            conflict = _primary_conflict(primary_public)
            if conflict:
                return done(
                    DateResolution(
                        DateConfidence.CONFLICTING,
                        candidate_public_date=min(c.value for c in primary_public).date(),
                        reason=conflict,
                    )
                )
        options = [*primary_public, *([submission] if submission else [])]
        first = min(options, key=lambda c: c.value)
        if first is submission:
            return done(
                DateResolution(
                    DateConfidence.VERIFIED,
                    first,
                    FirstPublicBasis.SUBMISSION_ONLY,
                    reason="arXiv submission time; the public announcement date was not captured",
                )
            )
        return done(
            DateResolution(
                DateConfidence.VERIFIED,
                first,
                PUBLIC_EVENTS[first.event],
                reason=f"{first.event.value} from the system of record "
                f"({first.reporting_source.value})",
            )
        )

    if not secondary:
        return done(
            DateResolution(
                DateConfidence.UNCERTAIN, reason="no day-precision public date from any source"
            )
        )

    earliest = min(secondary, key=lambda c: c.value)
    candidate = earliest.value.date()
    if max(c.value for c in secondary) - earliest.value > AGREEMENT:
        return done(
            DateResolution(
                DateConfidence.CONFLICTING,
                candidate_public_date=candidate,
                reason="secondary sources disagree and no system-of-record date is available",
            )
        )
    independent = _independent_pair(secondary)
    if independent is not None:
        first = min(independent, key=lambda c: c.value)
        return done(
            DateResolution(
                DateConfidence.CORROBORATED,
                first,
                _basis_for_secondary(first),
                reason="two claims with different, known upstream sources agree",
            )
        )
    if len({c.reporting_source for c in secondary}) > 1:
        return done(
            DateResolution(
                DateConfidence.SOURCE_AGREEMENT,
                candidate_public_date=candidate,
                reason="several sources agree, but they may share upstream data",
            )
        )
    return done(
        DateResolution(
            DateConfidence.SINGLE_SOURCE,
            candidate_public_date=candidate,
            reason=f"only {earliest.reporting_source.value} reports this date",
        )
    )


def _is_public(claim: DateClaim) -> bool:
    if claim.event not in PUBLIC_EVENTS:
        return False
    # Preprint events of later versions are version events, never a first appearance.
    return claim.version in (None, 1)


def _counts_as_secondary(claim: DateClaim) -> bool:
    return claim.event is DateEvent.REPORTED_PUBLICATION_DATE or _is_public(claim)


def _submission_only_fallback(usable: list[DateClaim]) -> DateClaim | None:
    """The arXiv v1 submission, for arXiv manifestations without a captured announcement."""
    announced = {c.manifestation_id for c in usable if c.event is DateEvent.PREPRINT_ANNOUNCED}
    submissions = [
        c
        for c in usable
        if c.event is DateEvent.PREPRINT_SUBMITTED
        and c.is_primary
        and c.reporting_source is ReportingSource.ARXIV_API
        and c.version in (None, 1)
        and c.manifestation_id not in announced
    ]
    return min(submissions, key=lambda c: c.value) if submissions else None


def _primary_conflict(primary: list[DateClaim]) -> str | None:
    groups: dict[tuple[uuid.UUID, DateEvent], list[DateClaim]] = defaultdict(list)
    for claim in primary:
        groups[(claim.manifestation_id, claim.event)].append(claim)
    for (_, event), group in groups.items():
        values = [c.value for c in group]
        if max(values) - min(values) > PRIMARY_CONFLICT:
            return f"primary {event.value} dates disagree by more than 2 days"
    return None


def _independent_pair(claims: list[DateClaim]) -> tuple[DateClaim, DateClaim] | None:
    # Only public-availability events can become a first appearance; a bare "publication
    # date" (reported_publication_date) can support but never establish one.
    known = [c for c in claims if c.upstream_source is not UpstreamSource.UNKNOWN and _is_public(c)]
    for i, a in enumerate(known):
        for b in known[i + 1 :]:
            if a.upstream_source is not b.upstream_source and abs(a.value - b.value) <= AGREEMENT:
                return a, b
    return None


def _basis_for_secondary(claim: DateClaim) -> FirstPublicBasis:
    return PUBLIC_EVENTS.get(claim.event, FirstPublicBasis.PUBLISHED_ONLINE)
