"""Version/reply links stated by sources, stored per manifestation (``paper_version_links``).

Only links with a defined meaning for the Version Matcher are stored (``LINK_STRENGTH``);
targets are normalised identifiers (arXiv DataCite DOIs become arXiv IDs).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from researchpilot.core.ids import uuid7
from researchpilot.domain.enums import SourceName
from researchpilot.domain.identifiers import (
    IdentifierScheme,
    InvalidIdentifier,
    arxiv_id_from_doi,
    normalize_arxiv,
    normalize_doi,
)
from researchpilot.services.matching.version_matcher import LINK_STRENGTH


@dataclass(frozen=True)
class StatedLink:
    link_type: str
    target_scheme: IdentifierScheme
    target_value: str
    evidence: dict[str, Any]


def target(id_type: str, value: str) -> tuple[IdentifierScheme, str] | None:
    try:
        if id_type == "doi":
            doi = normalize_doi(value)
            arxiv = arxiv_id_from_doi(doi)
            return (IdentifierScheme.ARXIV, arxiv) if arxiv else (IdentifierScheme.DOI, doi)
        if id_type == "arxiv":
            return IdentifierScheme.ARXIV, normalize_arxiv(value)[0]
    except InvalidIdentifier:
        return None
    return None


async def record_links(
    session: AsyncSession,
    paper_id: uuid.UUID,
    manifestation_id: uuid.UUID,
    source: SourceName,
    links: list[StatedLink],
    record_id: uuid.UUID | None,
) -> None:
    for link in links:
        if link.link_type not in LINK_STRENGTH:
            continue
        await session.execute(
            sa.text(
                "INSERT INTO paper_version_links (id, paper_id, manifestation_id, link_type, "
                "strength, target_scheme, target_value, source, evidence, source_record_id) "
                "VALUES (:id, :p, :m, :t, :st, :sc, :v, :s, CAST(:e AS jsonb), :r) "
                "ON CONFLICT (manifestation_id, link_type, target_scheme, target_value, source) "
                "DO NOTHING"
            ),
            {
                "id": uuid7(),
                "p": paper_id,
                "m": manifestation_id,
                "t": link.link_type,
                "st": LINK_STRENGTH[link.link_type],
                "sc": link.target_scheme.value,
                "v": link.target_value,
                "s": source.value,
                "e": json.dumps(link.evidence),
                "r": record_id,
            },
        )
