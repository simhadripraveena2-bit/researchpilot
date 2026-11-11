"""Builds the source clients for one process (API or worker)."""

from __future__ import annotations

from dataclasses import dataclass, replace

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot import __version__
from researchpilot.core.settings import Settings
from researchpilot.domain.enums import SourceName
from researchpilot.integrations.arxiv import ARXIV_POLICY, ArxivClient
from researchpilot.integrations.arxiv_feed import FEED_POLICY, ArxivFeedClient
from researchpilot.integrations.base import (
    PostgresHttpCache,
    PostgresRateLimiter,
    RateLimiter,
    SourceClient,
    SourceRecordStore,
)
from researchpilot.integrations.biorxiv import (
    BIORXIV_POLICY,
    MEDRXIV_POLICY,
    PreprintServerClient,
)
from researchpilot.integrations.crossref import CROSSREF_POLICY, CrossrefClient
from researchpilot.integrations.openalex import OPENALEX_POLICY, OpenAlexBudget, OpenAlexClient
from researchpilot.integrations.semantic_scholar import S2_POLICY, SemanticScholarClient


class _NoWait:
    async def acquire(self, source: SourceName, interval_seconds: float) -> None:
        return None


@dataclass
class Sources:
    http: httpx.AsyncClient
    records: SourceRecordStore
    arxiv: ArxivClient
    arxiv_feed: ArxivFeedClient
    crossref: CrossrefClient
    biorxiv: PreprintServerClient
    medrxiv: PreprintServerClient
    openalex: OpenAlexClient
    semantic_scholar: SemanticScholarClient

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
        arxiv_feed=ArxivFeedClient(SourceClient(FEED_POLICY, http, limiter, cache), records),
        crossref=CrossrefClient(SourceClient(CROSSREF_POLICY, http, limiter, cache), records),
        biorxiv=PreprintServerClient(SourceClient(BIORXIV_POLICY, http, limiter, cache), records),
        medrxiv=PreprintServerClient(SourceClient(MEDRXIV_POLICY, http, limiter, cache), records),
        openalex=OpenAlexClient(
            SourceClient(
                OPENALEX_POLICY,
                http,
                limiter,
                cache,
                headers=_bearer(settings.openalex_api_key),
                budget=OpenAlexBudget(settings.openalex_daily_budget_usd),
            ),
            records,
            settings.openalex_capabilities,
        ),
        semantic_scholar=SemanticScholarClient(
            SourceClient(
                # Without a key, a 429 (no Retry-After) does not clear by retrying: one attempt.
                S2_POLICY if settings.s2_api_key else replace(S2_POLICY, max_attempts=1),
                http,
                limiter,
                cache,
                headers=_key(settings.s2_api_key),
            ),
            records,
        ),
    )


def _bearer(secret: SecretStr | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret.get_secret_value()}"} if secret else {}


def _key(secret: SecretStr | None) -> dict[str, str]:
    return {"x-api-key": secret.get_secret_value()} if secret else {}
