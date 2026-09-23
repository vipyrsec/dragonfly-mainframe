"""Optional cache storage: bounded batches, immutable results, isolated DB pool."""

import datetime as dt
import hashlib
import logging
import threading
import time
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from functools import cache
from typing import Literal

from fastapi import HTTPException
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import Engine, create_engine, delete, func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mainframe.constants import mainframe_settings
from mainframe.models.orm import OpenGrepScan, Scan, ScanCacheEntry, ScanCacheNamespace, Status
from mainframe.models.scan_cache import (
    CacheContext,
    CacheKey,
    CacheLease,
    CacheLookup,
    CacheReply,
    CacheValue,
    CacheWriteReply,
)
from mainframe.rules import Rules

quarantined_entries = Counter(
    "scanner_cache_quarantined_total", "File results quarantined after validation", ["scanner"]
)
requests = Counter("scanner_cache_requests_total", "Durable cache operations", ["operation", "outcome"])
latency = Histogram("scanner_cache_request_seconds", "Durable cache operation duration", ["operation"])
rows_written = Counter("scanner_cache_rows_inserted_total", "New durable cache rows", ["scanner"])
rows_renewed = Counter("scanner_cache_rows_renewed_total", "Cache hits whose expiry was extended", ["scanner"])
cache_size = Gauge("scanner_cache_storage_bytes", "Physical cache bytes including indexes and TOAST")
cache_entries = Gauge("scanner_cache_entries", "Live cache entries across generations", ["scanner"])
cache_payload = Gauge("scanner_cache_payload_bytes", "Live serialized result bytes", ["scanner"])
rows_expired = Counter("scanner_cache_rows_expired_total", "Expired durable cache rows")
admission_skips = Counter("scanner_cache_admission_skips_total", "Entries skipped at capacity", ["scanner"])
_gate = threading.BoundedSemaphore(1)
_rate_lock = threading.Lock()
_recent_requests: deque[float] = deque()
MAX_REQUESTS_PER_SECOND = 10
MAX_NAMESPACES = 8
CLEANUP_BATCH = 100


@cache
def cache_engine() -> Engine:
    """Reserve at most one connection per API process, outside the queue pool."""
    return create_engine(
        mainframe_settings.db_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.05,
        connect_args={"connect_timeout": 2},
    )


def require_cache() -> None:
    if not mainframe_settings.scan_cache_enabled:
        raise HTTPException(404)
    with _rate_lock:
        now = time.monotonic()
        while _recent_requests and _recent_requests[0] <= now - 1:
            _recent_requests.popleft()
        if len(_recent_requests) >= MAX_REQUESTS_PER_SECOND:
            requests.labels("admission", "rate_limited").inc()
            raise HTTPException(429, "Cache rate limit; scan normally")
        _recent_requests.append(now)


def cache_session() -> Generator[Session, None, None]:
    if not _gate.acquire(blocking=False):
        requests.labels("admission", "busy").inc()
        raise HTTPException(503, "Cache busy; scan normally")
    try:
        with Session(cache_engine()) as session, session.begin():
            configure_transaction(session)
            yield session
        for scanner in ("yara", "opengrep"):
            rows_renewed.labels(scanner).inc(session.info.get(f"cache_renewed_{scanner}", 0))
    except SQLAlchemyError as error:
        # A failed COMMIT can leave psycopg2's connection in an aborted
        # transaction even after SQLAlchemy closes the session. The gate
        # excludes other users of this single-connection pool during disposal.
        cache_engine().dispose()
        requests.labels("database", "error").inc()
        logging.getLogger(__name__).warning("Durable scan cache unavailable", exc_info=True)
        raise HTTPException(503, "Cache unavailable; scan normally") from error
    finally:
        _gate.release()


def configure_transaction(session: Session) -> None:
    session.execute(text("SET LOCAL statement_timeout = '200ms'"))
    session.execute(text("SET LOCAL lock_timeout = '25ms'"))


def rules_digest(corpus: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name, contents in sorted(corpus.items()):
        for value in (name, contents):
            encoded = value.encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def validate_context(context: CacheContext, rules: Rules) -> None:
    corpus = rules.rules if context.scanner == "yara" else rules.opengrep_rules
    if context.rules_commit != rules.rules_commit or context.rules_digest != rules_digest(corpus):
        raise HTTPException(409, "Cache rules differ from current rules; scan normally")


def validate_lease(session: Session, scanner: str, lease: CacheLease, subject: str) -> None:
    model = Scan if scanner == "yara" else OpenGrepScan
    query = select(model).where(Scan.name == lease.name, Scan.version == lease.version)
    if scanner == "opengrep":
        query = query.join(Scan, Scan.scan_id == OpenGrepScan.scan_id)
    row = session.scalar(query)
    if (
        row is None
        or row.status != Status.PENDING
        or row.pending_by != subject
        or row.assignment_id != lease.assignment_id
        or row.attempt_count != lease.attempt
    ):
        raise HTTPException(409, "Cache writes require the current worker lease")


def lookup(session: Session, request: CacheLookup) -> CacheReply:
    namespace = request.context.namespace()
    generation = session.get(ScanCacheNamespace, namespace)
    if generation is None:
        return CacheReply()
    if generation.revoked:
        return CacheReply(revoked=True)
    keys = {(bytes.fromhex(key.file_digest), key.language) for key in request.keys}
    now = dt.datetime.now(dt.UTC)
    rows = session.scalars(
        select(ScanCacheEntry).where(
            ScanCacheEntry.namespace == namespace,
            tuple_(ScanCacheEntry.file_digest, ScanCacheEntry.language).in_(keys),
            ScanCacheEntry.expires_at > now,
            ScanCacheEntry.quarantined.is_(False),
        )
    ).all()
    renew_hits(session, request.context, list(rows), now)
    return CacheReply(
        entries=[
            CacheValue(file_digest=row.file_digest.hex(), language=row.language, result=row.result) for row in rows
        ]
    )


def renew_hits(session: Session, context: CacheContext, rows: list[ScanCacheEntry], now: dt.datetime) -> None:
    """Coalesce hot-key writes to hourly batches without reviving invalid entries."""
    ttl = mainframe_settings.scan_cache_ttl_seconds
    expires = now + dt.timedelta(seconds=ttl)
    cutoff = expires - dt.timedelta(seconds=min(3600, ttl / 2))
    keys = {(row.file_digest, row.language) for row in rows if row.expires_at <= cutoff}
    if not keys or not writer_lock(session, context.scanner):
        return
    renewed = session.scalars(
        update(ScanCacheEntry)
        .where(
            ScanCacheEntry.namespace == context.namespace(),
            tuple_(ScanCacheEntry.file_digest, ScanCacheEntry.language).in_(keys),
            ScanCacheEntry.expires_at > now,
            ScanCacheEntry.expires_at <= cutoff,
            ScanCacheEntry.quarantined.is_(False),
            select(ScanCacheNamespace.namespace)
            .where(ScanCacheNamespace.namespace == context.namespace(), ScanCacheNamespace.revoked.is_(False))
            .exists(),
        )
        .values(expires_at=expires)
        .returning(ScanCacheEntry.file_digest)
        .execution_options(synchronize_session=False)
    ).all()
    metric_key = f"cache_renewed_{context.scanner}"
    session.info[metric_key] = session.info.get(metric_key, 0) + len(renewed)


def quarantine(session: Session, context: CacheContext, keys: list[CacheKey]) -> CacheWriteReply:
    """Retain evidence and quota accounting; isolate only existing suspect keys."""
    changed = session.scalars(
        update(ScanCacheEntry)
        .where(
            ScanCacheEntry.namespace == context.namespace(),
            tuple_(ScanCacheEntry.file_digest, ScanCacheEntry.language).in_(
                {(bytes.fromhex(key.file_digest), key.language) for key in keys}
            ),
            ScanCacheEntry.quarantined.is_(False),
        )
        .values(quarantined=True)
        .returning(ScanCacheEntry.file_digest)
        .execution_options(synchronize_session=False)
    ).all()
    quarantined_entries.labels(context.scanner).inc(len(changed))
    return CacheWriteReply(quarantined=len(changed))


def writer_lock(session: Session, scanner: Literal["yara", "opengrep"]) -> bool:
    return bool(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(194731, :scanner)"), {"scanner": 1 if scanner == "yara" else 2}
        )
    )


def generation_for_write(session: Session, context: CacheContext) -> ScanCacheNamespace | None:
    generations = list(session.scalars(select(ScanCacheNamespace).where(ScanCacheNamespace.scanner == context.scanner)))
    for generation in generations:
        if generation.namespace == context.namespace():
            return generation
    if len(generations) >= MAX_NAMESPACES:
        return None
    generation = ScanCacheNamespace(
        namespace=context.namespace(),
        scanner=context.scanner,
        rules_commit=context.rules_commit,
        rules_digest=bytes.fromhex(context.rules_digest),
        engine_digest=bytes.fromhex(context.engine_digest),
    )
    session.add(generation)
    session.flush()
    return generation


def store(session: Session, context: CacheContext, values: list[CacheValue]) -> CacheWriteReply:
    disk_bytes = session.scalar(text("SELECT pg_total_relation_size('scan_cache_entries')"))
    if disk_bytes is not None and disk_bytes >= mainframe_settings.scan_cache_max_disk_bytes:
        admission_skips.labels(context.scanner).inc(len(values))
        return CacheWriteReply(skipped=len(values))
    generation = generation_for_write(session, context)
    if generation is None or generation.revoked:
        return CacheWriteReply(skipped=len(values))
    totals = session.execute(
        select(func.sum(ScanCacheNamespace.entry_count), func.sum(ScanCacheNamespace.payload_bytes)).where(
            ScanCacheNamespace.scanner == context.scanner
        )
    ).one()
    remaining_rows = max(0, mainframe_settings.scan_cache_max_entries - int(totals[0] or 0))
    remaining_bytes = max(0, mainframe_settings.scan_cache_max_bytes - int(totals[1] or 0))
    unique = {(value.file_digest, value.language): value for value in values}
    selected: list[dict[str, object]] = []
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=mainframe_settings.scan_cache_ttl_seconds)
    for value in unique.values():
        size = len(value.result.encode())
        if len(selected) >= remaining_rows or size > remaining_bytes:
            continue
        remaining_bytes -= size
        selected.append(
            {
                "namespace": generation.namespace,
                "file_digest": bytes.fromhex(value.file_digest),
                "language": value.language,
                "result": value.result,
                "expires_at": expires,
            }
        )
    inserted_bytes = (
        list(
            session.scalars(
                insert(ScanCacheEntry)
                .values(selected)
                .on_conflict_do_nothing()
                .returning(func.octet_length(ScanCacheEntry.result))
            )
        )
        if selected
        else []
    )
    generation.entry_count += len(inserted_bytes)
    generation.payload_bytes += sum(inserted_bytes)
    skipped = len(values) - len(inserted_bytes)
    rows_written.labels(context.scanner).inc(len(inserted_bytes))
    admission_skips.labels(context.scanner).inc(skipped)
    return CacheWriteReply(inserted=len(inserted_bytes), skipped=skipped)


def expire_entries(session: Session, scanner: Literal["yara", "opengrep"], current_rules: str) -> int:
    if not writer_lock(session, scanner):
        return 0
    expired_count = 0
    generations = session.scalars(select(ScanCacheNamespace).where(ScanCacheNamespace.scanner == scanner)).all()
    for generation in generations:
        if expired_count >= CLEANUP_BATCH:
            break
        victims = (
            select(ScanCacheEntry.file_digest, ScanCacheEntry.language)
            .where(
                ScanCacheEntry.namespace == generation.namespace,
                ScanCacheEntry.expires_at <= dt.datetime.now(dt.UTC),
            )
            .order_by(ScanCacheEntry.expires_at)
            .limit(CLEANUP_BATCH - expired_count)
        )
        sizes = session.scalars(
            delete(ScanCacheEntry)
            .where(
                ScanCacheEntry.namespace == generation.namespace,
                tuple_(ScanCacheEntry.file_digest, ScanCacheEntry.language).in_(victims),
            )
            .returning(func.octet_length(ScanCacheEntry.result))
            .execution_options(synchronize_session=False)
        ).all()
        generation.entry_count -= len(sizes)
        generation.payload_bytes -= sum(sizes)
        expired_count += len(sizes)
    session.flush()
    session.execute(
        delete(ScanCacheNamespace).where(
            ScanCacheNamespace.scanner == scanner,
            ScanCacheNamespace.entry_count == 0,
            (ScanCacheNamespace.rules_commit != current_rules) | ScanCacheNamespace.revoked.is_(False),
        )
    )
    return expired_count


def maintain_cache(current_rules: str) -> None:
    """Bound cleanup work per tick; idle caches remain physically bounded too."""
    if not mainframe_settings.scan_cache_enabled:
        return
    expired = 0
    with contextmanager(cache_session)() as session:
        expired = expire_entries(session, "yara", current_rules)
        expired += expire_entries(session, "opengrep", current_rules)
        cache_size.set(session.scalar(text("SELECT pg_total_relation_size('scan_cache_entries')")) or 0)
        for scanner in ("yara", "opengrep"):
            totals = session.execute(
                select(func.sum(ScanCacheNamespace.entry_count), func.sum(ScanCacheNamespace.payload_bytes)).where(
                    ScanCacheNamespace.scanner == scanner
                )
            ).one()
            cache_entries.labels(scanner).set(totals[0] or 0)
            cache_payload.labels(scanner).set(totals[1] or 0)
    rows_expired.inc(expired)
