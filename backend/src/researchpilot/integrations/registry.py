"""Builds the source clients for one process (API or worker)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot import __version__
from researchpilot.core.settings import Settings
from researchpilot.domain.enums import SourceName
from researchpilot.integrations.arxiv import ARXIV_POLICY, ArxivClient
from researchpilot.integrations.base import (
    PostgresHttpCache,
    PostgresRateLimiter,
    RateLimiter,
    SourceClient,
    SourceRecordStore,
)


class _NoWait:
    async def acquire(self, source: SourceName, interval_seconds: float) -> None:
        return None


@dataclass
class Sources:
    http: httpx.AsyncClient
    records: SourceRecordStore
    arxiv: ArxivClient

    async def aclose(self) -> None:
        await self.http.aclose()


def user_agent(settings: Settings) -> str:
    # A contact address is sent only when the operator configured one (CONTACT_EMAIL).
    contact = f"; mailto:{settings.contact_email}" if settings.contact_email else ""
    return f"ResearchPilot/{__version__} (research-assistant{contact})"


def build_sources(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    transport: httpx.AsyncBaseTransport | None = None,
    *,
    rate_limits: bool = True,
) -> Sources:
    """``rate_limits=False`` is for tests with recorded responses only (no real requests)."""
    http = httpx.AsyncClient(
        transport=transport,
        headers={"User-Agent": user_agent(settings)},
        follow_redirects=True,
    )
    limiter: RateLimiter = PostgresRateLimiter(sessions) if rate_limits else _NoWait()
    cache = PostgresHttpCache(sessions)
    records = SourceRecordStore(sessions)
    return Sources(
        http=http,
        records=records,
        arxiv=ArxivClient(SourceClient(ARXIV_POLICY, http, limiter, cache), records),
    )
