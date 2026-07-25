import datetime as dt
from threading import Lock
from typing import cast

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from mainframe.metrics import (
    packages_in_queue,
    packages_queue,
    packages_queue_oldest_age_seconds,
    packages_queue_snapshot_timestamp_seconds,
)
from mainframe.models.orm import Scan, Status
from mainframe.models.schemas import QueueStatus


def read_queue_status(session: Session, *, now: dt.datetime, job_timeout: int) -> QueueStatus:
    """Read all queue states with one indexed aggregate query."""
    retry_before = now - dt.timedelta(seconds=job_timeout)
    retryable = (Scan.status == Status.PENDING) & (Scan.pending_at < retry_before)
    stranded = (Scan.status == Status.PENDING) & Scan.pending_at.is_(None)
    backlog = (Scan.status == Status.QUEUED) | retryable
    query = (
        select(
            func.count().filter(Scan.status == Status.QUEUED),
            func.count().filter((Scan.status == Status.PENDING) & (Scan.pending_at >= retry_before)),
            func.count().filter(retryable),
            func.count().filter(stranded),
            func.min(Scan.queued_at).filter(backlog),
        )
        .select_from(Scan)
        .where((Scan.status == Status.QUEUED) | (Scan.status == Status.PENDING))
    )

    row = session.execute(query).one()
    queued = int(row[0])
    in_progress = int(row[1])
    retryable_count = int(row[2])
    stranded_count = int(row[3])
    oldest_queued_at = cast("dt.datetime | None", row[4])
    oldest_age_seconds = None
    if oldest_queued_at is not None:
        if oldest_queued_at.tzinfo is None:
            oldest_queued_at = oldest_queued_at.replace(tzinfo=dt.UTC)
        oldest_age_seconds = max(0, int((now - oldest_queued_at).total_seconds()))

    return QueueStatus(
        queued=queued,
        in_progress=in_progress,
        retryable=retryable_count,
        stranded=stranded_count,
        total_backlog=queued + retryable_count,
        oldest_queued_at=oldest_queued_at,
        oldest_age_seconds=oldest_age_seconds,
        sampled_at=now,
    )


def update_queue_metrics(snapshot: QueueStatus) -> None:
    """Publish one database snapshot to Prometheus without querying during scrapes."""
    packages_queue.labels(state="queued").set(snapshot.queued)
    packages_queue.labels(state="in_progress").set(snapshot.in_progress)
    packages_queue.labels(state="retryable").set(snapshot.retryable)
    packages_queue.labels(state="stranded").set(snapshot.stranded)
    packages_in_queue.set(snapshot.queued + snapshot.in_progress + snapshot.retryable + snapshot.stranded)
    packages_queue_oldest_age_seconds.set(snapshot.oldest_age_seconds or 0)
    packages_queue_snapshot_timestamp_seconds.set(snapshot.sampled_at.timestamp())


class QueueMonitor:
    """Periodically refreshed, process-local view of durable database queue state."""

    def __init__(self, engine: Engine, *, job_timeout: int) -> None:
        self.engine = engine
        self.job_timeout = job_timeout
        self._snapshot: QueueStatus | None = None
        self._lock = Lock()

    def refresh(self, *, now: dt.datetime | None = None) -> QueueStatus:
        sampled_at = now or dt.datetime.now(dt.UTC)
        with Session(bind=self.engine) as session, session.begin():
            snapshot = read_queue_status(session, now=sampled_at, job_timeout=self.job_timeout)

        update_queue_metrics(snapshot)
        with self._lock:
            self._snapshot = snapshot
        return snapshot

    def get_snapshot(self) -> QueueStatus | None:
        with self._lock:
            return self._snapshot
