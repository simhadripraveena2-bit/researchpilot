"""Record the source responses of one real discovery run as test fixtures.

Usage (needs network access to the sources and a local PostgreSQL):

    uv run python scripts/record_discovery_fixtures.py postgresql+psycopg://.../rp_record

Runs the discovery workflow for ``tests/fixtures/discovery.py`` against the real APIs and
writes every response (arXiv, Crossref, OpenAlex, bioRxiv/medRxiv) to
``tests/fixtures/sources/<source>/`` with an entry in that directory's ``_recorded.json``.
Semantic Scholar requests carry the key the environment injects (never in the URL or the
recording). Tests replay them with a placeholder key. Existing fixtures are never overwritten.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

import httpx
import sqlalchemy as sa
from tests.fixtures.discovery import OBJECTIVE, RUN_CONFIG

from researchpilot.core.ids import uuid7
from researchpilot.core.settings import Settings
from researchpilot.db.session import make_engine, make_sessionmaker, session_scope
from researchpilot.services.discovery.runs import start_discovery
from researchpilot.services.objectives.model import ObjectiveContent
from researchpilot.services.objectives.service import create_objective
from researchpilot.worker.main import build_worker

SOURCES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sources"
DIRS = {
    "export.arxiv.org": "arxiv",
    "api.crossref.org": "crossref",
    "api.openalex.org": "openalex",
    "api.biorxiv.org": "biorxiv",
    "api.semanticscholar.org": "semantic_scholar",
}


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(trust_env=True, timeout=60)
        self.saved: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._client.send(
            httpx.Request(request.method, request.url, headers=request.headers)
        )
        body = response.text
        directory = DIRS.get(request.url.host)
        if directory is not None:
            self._save(directory, request, response, body)
        headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
        }
        return httpx.Response(response.status_code, text=body, headers=headers)

    def _save(
        self, directory: str, request: httpx.Request, response: httpx.Response, body: str
    ) -> None:
        folder = SOURCES / directory
        url = str(request.url)
        ids = request.url.params.get("id_list")
        if directory == "arxiv" and ids is not None:
            name = "api_" + ids.replace("/", "_").replace(",", "+") + ".xml"
            if not (folder / name).exists():
                (folder / name).write_text(body)
                self.saved.append(name)
            return  # id_list lookups are served by file name
        if directory == "crossref" and request.url.path.startswith("/works/"):
            name = "works_" + quote(request.url.path.removeprefix("/works/"), safe="") + ".json"
        else:
            digest = hashlib.sha256(url.encode()).hexdigest()[:12]
            ext = ".xml" if directory == "arxiv" else ".json"
            name = f"discovery_{digest}{ext}"
        log_path = folder / "_recorded.json"
        log = json.loads(log_path.read_text()) if log_path.exists() else {}
        if name in log or (folder / name).exists():
            return
        (folder / name).write_text(body)

        def keep(header: str) -> bool:  # budget and rate-limit headers drive the clients
            h = header.lower()
            return h in ("content-type", "retry-after") or h.startswith("x-ratelimit")

        log[name] = {
            "url": url,
            "status": response.status_code,
            "headers": {k: v for k, v in response.headers.items() if keep(k)},
            "recorded": date.today().isoformat(),
            "note": "recorded by scripts/record_discovery_fixtures.py",
        }
        log_path.write_text(json.dumps(log, indent=1, sort_keys=True))  # existing format
        self.saved.append(f"{directory}/{name}")


async def main(database_url: str) -> None:
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        llm_force_fake=True,
        arxiv_capture_enabled=False,
    )
    sessions = make_sessionmaker(make_engine(database_url))
    async with session_scope(sessions) as s:
        user, project = uuid7(), uuid7()
        await s.execute(
            sa.text("INSERT INTO users (id, display_name) VALUES (:u, 'rec')"), {"u": user}
        )
        await s.execute(
            sa.text(
                "INSERT INTO projects (id, user_id, title, topic, expertise_level, goal) "
                "VALUES (:p, :u, 't', 't', 'advanced', 'review_literature')"
            ),
            {"p": project, "u": user},
        )
        await create_objective(s, project, user, ObjectiveContent.model_validate(OBJECTIVE))
        run_id = await start_discovery(s, project, RUN_CONFIG, {})
    transport = RecordingTransport()
    worker, close = await build_worker(settings, source_transport=transport)
    try:
        while await worker.tick():
            pass
    finally:
        await close()
    async with session_scope(sessions) as s:
        status = await s.scalar(
            sa.text("SELECT status FROM research_runs WHERE id = :id"), {"id": run_id}
        )
    print(f"run {run_id}: {status}; saved {len(transport.saved)} files")
    for name in transport.saved:
        print(" ", name)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
