"""Run a benchmark split and write its report.

    uv run python scripts/run_benchmarks.py benchmarks/g_match/b0.json \
        --admin-url postgresql://postgres:postgres@127.0.0.1:5432/postgres \
        --out ../docs/evaluation/reports

Creates a scratch database (migrated, dropped afterwards), runs every case from recorded
responses and writes ``<benchmark>-<split>.md`` / ``.json``. ``--record`` fetches and saves
system-of-record responses that are not recorded yet (B0 maintenance only; needs network).
B3 is refused unless run by the custodian from custodian storage (see cases.guard_split).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config

from researchpilot.evaluation import gdates, gmatch, report
from researchpilot.evaluation.cases import Split, load_dataset
from researchpilot.evaluation.harness import bench
from researchpilot.services.matching.version_matcher import RULE_VERSION as MATCHER_RULES

BACKEND = Path(__file__).resolve().parents[1]


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],  # noqa: S607
            cwd=BACKEND,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", "src", "benchmarks"],  # noqa: S607
            cwd=BACKEND,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out + ("+uncommitted-changes" if dirty else "")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def scratch_database(admin_url: str) -> tuple[str, str]:
    name = f"rp_bench_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = admin_url.rsplit("/", 1)[0] + "/" + name
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.attributes["database_url"] = url.replace("postgresql://", "postgresql+psycopg://", 1)
    command.upgrade(cfg, "head")
    return name, url


async def run(path: Path, admin_url: str, out: Path, record: bool) -> int:
    dataset = load_dataset(path)
    if record and dataset.split is not Split.B0:
        print("recording is for B0 maintenance only", file=sys.stderr)
        return 2
    roots = [(path.parent / r).resolve() for r in dataset.recordings]
    name, url = scratch_database(admin_url)
    try:
        async with bench(
            url.replace("postgresql://", "postgresql+psycopg://", 1),
            roots,
            record_to=roots[0] if record else None,
        ) as b:
            if dataset.benchmark == "G-MATCH":
                results, metrics = await gmatch.run(b, dataset)
                rows = gmatch.as_dicts(results)
            else:
                date_results, metrics = await gdates.run(b, dataset)
                rows = gdates.as_dicts(date_results)
            if record:
                print("recorded:", *b.transport.recorded_now, sep="\n  ")
    finally:
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    run_info = {
        "git_sha": _git_sha(),
        "version_matcher_rules": MATCHER_RULES,
        "dataset_sha256": _digest(path),
        "recordings": ", ".join(str(r.relative_to(BACKEND)) for r in roots),
    }
    markdown, payload = report.build(dataset, rows, metrics, run_info)
    written = report.write(out, dataset, markdown, payload)
    print(f"{dataset.benchmark} {dataset.split.value}: {payload['verdict']}\n-> {written}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("datasets", nargs="+", type=Path)
    parser.add_argument("--admin-url", required=True)
    parser.add_argument("--out", type=Path, default=BACKEND.parent / "docs/evaluation/reports")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    for path in args.datasets:
        code = asyncio.run(run(path, args.admin_url, args.out, args.record))
        if code:
            sys.exit(code)


if __name__ == "__main__":
    main()
