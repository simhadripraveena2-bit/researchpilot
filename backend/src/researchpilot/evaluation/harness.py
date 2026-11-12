"""Benchmark environment: a scratch database, replayed sources and the real code paths.

Each case starts from an empty paper store and a new project, then runs exactly what the
product runs: ``add_paper_by_identifier`` (system-of-record ingestion, version links, the
Version Matcher, the Date Resolver, enrichment), announcement capture, and split/merge for
reversibility. Nothing is mocked except the network:

* systems of record (arXiv, Crossref, bioRxiv/medRxiv, arXiv RSS) are replayed; a request
  with no recording makes the case **not evaluable** (reported, never scored);
* aggregator lookups (OpenAlex, Semantic Scholar) without a recording get a 503 "not
  recorded" answer, i.e. the case is evaluated as if that aggregator were unavailable (as it
  often is); which aggregator answers a case had is reported.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.ids import uuid7
from researchpilot.core.settings import Settings
from researchpilot.db.session import make_engine, make_sessionmaker, session_scope
from researchpilot.evaluation.replay import ReplayTransport
from researchpilot.integrations.registry import Sources, build_sources
from researchpilot.services.matching.store import active_work
from researchpilot.services.papers.service import add_paper_by_identifier

SYSTEMS_OF_RECORD = frozenset(
    {"export.arxiv.org", "api.crossref.org", "api.biorxiv.org", "rss.arxiv.org"}
)
AGGREGATORS = frozenset({"api.openalex.org", "api.semanticscholar.org"})


@dataclass
class CaseTrace:
    """What the network did for one case."""

    missing: list[str] = field(default_factory=list)  # unrecorded system-of-record requests
    aggregators_unrecorded: set[str] = field(default_factory=set)
    aggregators_answered: set[str] = field(default_factory=set)


class BenchTransport(ReplayTransport):
    def __init__(self, roots: list[Path], record_to: Path | None = None) -> None:
        self.trace = CaseTrace()
        super().__init__(
            roots,
            unrecorded=self._unrecorded_answer,
            record_to=record_to,
            live_hosts=SYSTEMS_OF_RECORD if record_to is not None else (),
        )

    def _unrecorded_answer(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host in AGGREGATORS:
            self.trace.aggregators_unrecorded.add(host)
            return httpx.Response(503, text="not recorded for this benchmark")
        self.trace.missing.append(str(request.url))
        return httpx.Response(599, text="not recorded")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        if request.url.host in AGGREGATORS and response.status_code < 500:
            self.trace.aggregators_answered.add(request.url.host)
        return response


@dataclass
class Bench:
    sessions: async_sessionmaker[AsyncSession]
    sources: Sources
    transport: BenchTransport
    user_id: uuid.UUID
    settings: Settings
    rate_limits: bool

    async def reset(self) -> uuid.UUID:
        """Empty paper store (works are global), fresh source clients and a new project;
        returns the project.

        Fresh clients matter: a source's circuit breaker opened by one case's unavailable
        aggregator must not make the next case run without that aggregator (cases are
        independent and order-free)."""
        self.transport.trace = CaseTrace()
        await self.sources.aclose()
        self.sources = build_sources(
            self.settings, self.sessions, self.transport, rate_limits=self.rate_limits
        )
        async with session_scope(self.sessions) as session:
            for statement in (
                "DELETE FROM research_items WHERE item_type = 'paper'",
                "DELETE FROM source_records",
                "DELETE FROM http_cache",
                "DELETE FROM source_rate_limits",
                "DELETE FROM arxiv_announcement_log",
            ):
                await session.execute(sa.text(statement))
            project_id = uuid7()
            await session.execute(
                sa.text(
                    "INSERT INTO projects (id, user_id, title, topic, expertise_level, goal) "
                    "VALUES (:p, :u, 'benchmark', 'benchmark', 'advanced', 'review_literature')"
                ),
                {"p": project_id, "u": self.user_id},
            )
            await session.execute(
                sa.text(
                    "INSERT INTO project_members (project_id, user_id, role) "
                    "VALUES (:p, :u, 'owner')"
                ),
                {"p": project_id, "u": self.user_id},
            )
        return project_id

    async def add(self, project_id: uuid.UUID, identifier: str) -> uuid.UUID:
        async with session_scope(self.sessions) as session:
            paper_id, _, _ = await add_paper_by_identifier(
                session, self.sources, project_id, identifier
            )
        return paper_id

    async def active(self, paper_id: uuid.UUID) -> uuid.UUID:
        async with session_scope(self.sessions) as session:
            return await active_work(session, paper_id)


@asynccontextmanager
async def bench(
    database_url: str, roots: list[Path], record_to: Path | None = None
) -> AsyncIterator[Bench]:
    """``database_url``: a migrated database used only for benchmarks (its paper data is
    deleted between cases)."""
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        llm_force_fake=True,
        arxiv_capture_enabled=False,
        s2_api_key=None,
        openalex_api_key=None,
    )
    engine = make_engine(database_url)
    sessions = make_sessionmaker(engine)
    transport = BenchTransport(roots, record_to)
    sources = build_sources(settings, sessions, transport, rate_limits=record_to is not None)
    async with session_scope(sessions) as session:
        user_id = await session.scalar(
            sa.text(
                "INSERT INTO users (id, display_name, auth_provider) VALUES (:id, "
                "'benchmark runner', 'password') RETURNING id"
            ),
            {"id": uuid7()},
        )
    try:
        yield (b := Bench(sessions, sources, transport, user_id, settings, record_to is not None))
    finally:
        await b.sources.aclose()
        await transport.aclose()
        async with session_scope(sessions) as session:
            await session.execute(sa.text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await engine.dispose()
