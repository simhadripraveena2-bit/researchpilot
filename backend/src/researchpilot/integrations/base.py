"""``SourceClient``: the only way to call an external scholarly API (ARCHITECTURE §4.1, S5).

Every request goes through:

1. the **HTTP cache** (Postgres, TTL per endpoint class); a hit makes no request;
2. the **rate limiter**: one request slot per ``min_interval`` per source, shared by every
   process through ``source_rate_limits`` (R1-4: arXiv <= 1 request / 3 s);
3. **retries** on connection errors, 429 and 5xx with jittered exponential backoff, honouring
   ``Retry-After`` (seconds or HTTP date) up to a cap;
4. a **circuit breaker**: after ``breaker_threshold`` consecutive failed requests the source is
   *degraded* for ``breaker_cooldown`` and calls fail fast with ``SourceDegraded``, so a run
   can finish as partially succeeded with a coverage notice.

Raw entity payloads are stored with ``SourceRecordStore.save`` (once per distinct content).
"""

from __future__ import annotations

import asyncio
import email.utils
import hashlib
import json
import random
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from researchpilot.core.clock import Clock, SystemClock
from researchpilot.core.errors import DependencyUnavailable
from researchpilot.core.ids import uuid7
from researchpilot.domain.enums import SourceName

log = structlog.get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]


class SourceError(DependencyUnavailable):
    """A source request failed after retries (the run continues with reduced coverage)."""

    code = "source_unavailable"

    def __init__(
        self, source: SourceName, detail: str, *, upstream_status: int | None = None
    ) -> None:
        super().__init__(detail, source=source.value, upstream_status=upstream_status)
        self.source = source
        self.upstream_status = upstream_status


class SourceDegraded(SourceError):
    """The circuit breaker is open: the source failed repeatedly and is skipped for now."""

    code = "source_degraded"


class SourceNotFound(SourceError):
    """The source has no such entity (404 or an empty lookup result)."""

    code, status, title = "source_not_found", 404, "Not found at the source"


@dataclass(frozen=True)
class SourcePolicy:
    source: SourceName
    min_interval_seconds: float
    max_attempts: int = 4
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    retry_after_cap_seconds: float = 120.0
    breaker_threshold: int = 3
    breaker_cooldown: timedelta = timedelta(minutes=10)
    timeout_seconds: float = 30.0
    cache_ttl: Mapping[str, timedelta] = field(default_factory=dict)
    default_cache_ttl: timedelta = timedelta(days=1)

    def ttl(self, endpoint_class: str) -> timedelta:
        return self.cache_ttl.get(endpoint_class, self.default_cache_ttl)


@dataclass(frozen=True)
class SourceResponse:
    source: SourceName
    url: str
    status: int
    text: str
    headers: Mapping[str, str]
    fetched_at: datetime
    cache_hit: bool
    endpoint_class: str


class RateLimiter(Protocol):
    async def acquire(self, source: SourceName, interval_seconds: float) -> None: ...


class HttpCache(Protocol):
    async def get(self, key: str) -> SourceResponse | None: ...

    async def put(self, key: str, response: SourceResponse, expires_at: datetime) -> None: ...


# --- rate limiting ---------------------------------------------------------------------------


class PostgresRateLimiter:
    """Reserves the next free slot atomically, so concurrent processes never share a slot.

    ``next_slot_at`` moves forward by one interval per reservation; the caller sleeps until
    its slot. No lock is held while waiting.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession], sleep: Sleep = asyncio.sleep):
        self._sessions = sessions
        self._sleep = sleep

    async def acquire(self, source: SourceName, interval_seconds: float) -> None:
        async with self._sessions() as session, session.begin():
            wait = (
                await session.execute(
                    sa.text(
                        "INSERT INTO source_rate_limits AS l (source, next_slot_at) "
                        "VALUES (:s, now() + make_interval(secs => :i)) "
                        "ON CONFLICT (source) DO UPDATE SET next_slot_at = "
                        "greatest(l.next_slot_at, now()) + make_interval(secs => :i) "
                        "RETURNING extract(epoch FROM (l.next_slot_at - make_interval(secs => :i)"
                        " - now()))"
                    ),
                    {"s": source.value, "i": interval_seconds},
                )
            ).scalar_one()
        if wait and float(wait) > 0:
            await self._sleep(float(wait))


class InProcessRateLimiter:
    """Single-process limiter on an injectable clock (unit tests, scripts)."""

    def __init__(self, clock: Clock | None = None, sleep: Sleep = asyncio.sleep) -> None:
        self._clock = clock or SystemClock()
        self._sleep = sleep
        self._next: dict[SourceName, datetime] = {}
        self._lock = asyncio.Lock()
        self.waits: list[float] = []

    async def acquire(self, source: SourceName, interval_seconds: float) -> None:
        async with self._lock:
            now = self._clock.now()
            slot = max(self._next.get(source, now), now)
            self._next[source] = slot + timedelta(seconds=interval_seconds)
        wait = (slot - now).total_seconds()
        self.waits.append(wait)
        if wait > 0:
            await self._sleep(wait)


# --- HTTP cache ------------------------------------------------------------------------------


def cache_key(source: SourceName, url: str, params: Mapping[str, Any] | None) -> str:
    canonical = json.dumps(
        {"s": source.value, "u": url, "p": sorted((params or {}).items())}, default=str
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class PostgresHttpCache:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock | None = None):
        self._sessions = sessions
        self._clock = clock or SystemClock()

    async def get(self, key: str) -> SourceResponse | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    sa.text(
                        "SELECT source, url, status, headers, body, fetched_at FROM http_cache "
                        "WHERE key = :k AND expires_at > :now"
                    ),
                    {"k": key, "now": self._clock.now()},
                )
            ).first()
        if row is None:
            return None
        headers = dict(row.headers)
        return SourceResponse(
            source=SourceName(row.source),
            url=row.url,
            status=row.status,
            text=row.body,
            headers=headers,
            fetched_at=row.fetched_at,
            cache_hit=True,
            endpoint_class=str(headers.get("x-rp-endpoint-class", "")),
        )

    async def put(self, key: str, response: SourceResponse, expires_at: datetime) -> None:
        headers = {**response.headers, "x-rp-endpoint-class": response.endpoint_class}
        async with self._sessions() as session, session.begin():
            await session.execute(
                sa.text(
                    "INSERT INTO http_cache (key, source, url, status, headers, body, fetched_at, "
                    "expires_at) VALUES (:k, :s, :u, :st, CAST(:h AS jsonb), :b, :f, :e) "
                    "ON CONFLICT (key) DO UPDATE SET status = excluded.status, "
                    "headers = excluded.headers, body = excluded.body, "
                    "fetched_at = excluded.fetched_at, expires_at = excluded.expires_at"
                ),
                {
                    "k": key,
                    "s": response.source.value,
                    "u": response.url,
                    "st": response.status,
                    "h": json.dumps(headers),
                    "b": response.text,
                    "f": response.fetched_at,
                    "e": expires_at,
                },
            )


class MemoryHttpCache:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()
        self._entries: dict[str, tuple[SourceResponse, datetime]] = {}

    async def get(self, key: str) -> SourceResponse | None:
        entry = self._entries.get(key)
        if entry is None or entry[1] <= self._clock.now():
            return None
        response, _ = entry
        return SourceResponse(**{**response.__dict__, "cache_hit": True})

    async def put(self, key: str, response: SourceResponse, expires_at: datetime) -> None:
        self._entries[key] = (response, expires_at)


# --- source records --------------------------------------------------------------------------


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class SourceRecordStore:
    """Stores raw entity payloads; the same content is stored once (UNIQUE on its hash)."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save(
        self,
        source: SourceName,
        source_entity_id: str,
        endpoint: str,
        payload: Mapping[str, Any],
        fetched_at: datetime,
    ) -> uuid.UUID:
        digest = payload_sha256(payload)
        async with self._sessions() as session, session.begin():
            inserted = (
                await session.execute(
                    sa.text(
                        "INSERT INTO source_records (id, source, source_entity_id, endpoint, "
                        "payload, payload_sha256, fetched_at) "
                        "VALUES (:id, :s, :e, :ep, CAST(:p AS jsonb), :h, :f) "
                        "ON CONFLICT (source, source_entity_id, payload_sha256) DO NOTHING "
                        "RETURNING id"
                    ),
                    {
                        "id": uuid7(),
                        "s": source.value,
                        "e": source_entity_id,
                        "ep": endpoint,
                        "p": json.dumps(payload, default=str),
                        "h": digest,
                        "f": fetched_at,
                    },
                )
            ).scalar_one_or_none()
            if inserted is not None:
                return uuid.UUID(str(inserted))
            existing = (
                await session.execute(
                    sa.text(
                        "SELECT id FROM source_records WHERE source = :s AND "
                        "source_entity_id = :e AND payload_sha256 = :h"
                    ),
                    {"s": source.value, "e": source_entity_id, "h": digest},
                )
            ).scalar_one()
            return uuid.UUID(str(existing))


# --- the client ------------------------------------------------------------------------------

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class SourceClient:
    """Base for every source integration. Subclasses build URLs and parse payloads."""

    def __init__(
        self,
        policy: SourcePolicy,
        http: httpx.AsyncClient,
        limiter: RateLimiter,
        cache: HttpCache,
        *,
        clock: Clock | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.policy = policy
        self.source = policy.source
        self._http = http
        self._limiter = limiter
        self._cache = cache
        self._clock = clock or SystemClock()
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 - jitter, not security
        self._consecutive_failures = 0
        self._degraded_until: datetime | None = None
        self.requests_made = 0

    @property
    def degraded(self) -> bool:
        return self._degraded_until is not None and self._clock.now() < self._degraded_until

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        endpoint_class: str = "default",
        use_cache: bool = True,
        not_found_ok: bool = False,
    ) -> SourceResponse:
        key = cache_key(self.source, url, params)
        if use_cache:
            cached = await self._cache.get(key)
            if cached is not None:
                log.info("source.cache_hit", source=self.source.value, url=url)
                return cached
        if self.degraded:
            raise SourceDegraded(self.source, f"{self.source.value} is temporarily unavailable")

        response = await self._request_with_retries(url, params)
        result = SourceResponse(
            source=self.source,
            url=str(response.request.url),
            status=response.status_code,
            text=response.text,
            headers={
                k.lower(): v
                for k, v in response.headers.items()
                if k.lower() in ("content-type", "etag", "last-modified")
            },
            fetched_at=self._clock.now(),
            cache_hit=False,
            endpoint_class=endpoint_class,
        )
        if response.status_code == 404:
            if not_found_ok:
                return result
            raise SourceNotFound(self.source, "not found at the source", upstream_status=404)
        if use_cache and response.status_code == 200:
            await self._cache.put(key, result, self._clock.now() + self.policy.ttl(endpoint_class))
        return result

    async def _request_with_retries(
        self, url: str, params: Mapping[str, Any] | None
    ) -> httpx.Response:
        last_error = "no attempt made"
        status: int | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            await self._limiter.acquire(self.source, self.policy.min_interval_seconds)
            retry_after: float | None = None
            try:
                self.requests_made += 1
                response = await self._http.get(
                    url, params=params, timeout=self.policy.timeout_seconds
                )
            except httpx.TransportError as exc:
                last_error, status = f"connection error: {type(exc).__name__}", None
            else:
                if response.status_code not in RETRYABLE_STATUS:
                    if response.status_code < 400 or response.status_code == 404:
                        self._consecutive_failures = 0
                        return response
                    # Other 4xx: our request is wrong; retrying cannot help.
                    self._record_failure()
                    raise SourceError(
                        self.source,
                        f"{self.source.value} rejected the request ({response.status_code})",
                        upstream_status=response.status_code,
                    )
                last_error, status = f"HTTP {response.status_code}", response.status_code
                retry_after = parse_retry_after(response.headers.get("retry-after"), self._clock)
            log.warning(
                "source.retry",
                source=self.source.value,
                attempt=attempt,
                error=last_error,
                retry_after=retry_after,
            )
            if attempt == self.policy.max_attempts:
                break
            if retry_after is not None and retry_after > self.policy.retry_after_cap_seconds:
                break  # the source asks us to wait longer than a run should block
            await self._sleep(retry_after if retry_after is not None else self._backoff(attempt))
        self._record_failure()
        raise SourceError(
            self.source,
            f"{self.source.value} did not respond successfully ({last_error})",
            upstream_status=status,
        )

    def _backoff(self, attempt: int) -> float:
        ceiling = min(
            self.policy.backoff_max_seconds, self.policy.backoff_base_seconds * 2 ** (attempt - 1)
        )
        return self._rng.uniform(ceiling / 2, ceiling)  # jittered

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.policy.breaker_threshold:
            self._degraded_until = self._clock.now() + self.policy.breaker_cooldown
            log.warning(
                "source.degraded", source=self.source.value, until=self._degraded_until.isoformat()
            )


def parse_retry_after(value: str | None, clock: Clock) -> float | None:
    """``Retry-After`` as delay-seconds or an HTTP date (RFC 9110 §10.2.3)."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return float(text)
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - clock.now()).total_seconds())
