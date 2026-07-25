import datetime as dt

import pytest
from fastapi import HTTPException, status
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from mainframe.endpoints.queue import queue_status
from mainframe.models.orm import Scan, Status
from mainframe.queue_monitor import QueueMonitor, read_queue_status


def replace_queue(session: Session, scans: list[Scan]) -> None:
    with session.begin():
        session.execute(update(Scan).values(status=Status.FINISHED))
        session.add_all(scans)


def test_queue_status_distinguishes_durable_states(db_session: Session) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_queue(
        db_session,
        [
            Scan(
                name="queued",
                version="1",
                status=Status.QUEUED,
                queued_at=now - dt.timedelta(minutes=5),
                queued_by="test",
            ),
            Scan(
                name="active",
                version="1",
                status=Status.PENDING,
                queued_at=now - dt.timedelta(minutes=4),
                queued_by="test",
                pending_at=now - dt.timedelta(seconds=30),
            ),
            Scan(
                name="retryable",
                version="1",
                status=Status.PENDING,
                queued_at=now - dt.timedelta(minutes=10),
                queued_by="test",
                pending_at=now - dt.timedelta(minutes=3),
            ),
            Scan(
                name="missing-pending-time",
                version="1",
                status=Status.PENDING,
                queued_at=now - dt.timedelta(minutes=2),
                queued_by="test",
            ),
            Scan(
                name="finished",
                version="1",
                status=Status.FINISHED,
                queued_at=now - dt.timedelta(minutes=20),
                queued_by="test",
            ),
        ],
    )

    with db_session.begin():
        snapshot = read_queue_status(db_session, now=now, job_timeout=120)

    assert snapshot.queued == 1
    assert snapshot.in_progress == 1
    assert snapshot.retryable == 1
    assert snapshot.stranded == 1
    assert snapshot.total_backlog == 2
    assert snapshot.oldest_queued_at == now - dt.timedelta(minutes=10)
    assert snapshot.oldest_age_seconds == 600
    assert snapshot.sampled_at == now


def test_queue_status_handles_an_empty_queue(db_session: Session) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_queue(db_session, [])

    with db_session.begin():
        snapshot = read_queue_status(db_session, now=now, job_timeout=120)

    assert snapshot.total_backlog == 0
    assert snapshot.stranded == 0
    assert snapshot.oldest_queued_at is None
    assert snapshot.oldest_age_seconds is None


def test_queue_monitor_caches_latest_snapshot(db_session: Session, engine: Engine) -> None:
    now = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    replace_queue(db_session, [])
    monitor = QueueMonitor(engine, job_timeout=120)

    assert monitor.get_snapshot() is None

    snapshot = monitor.refresh(now=now)

    assert monitor.get_snapshot() == snapshot
    assert queue_status(monitor) == snapshot
    assert snapshot.model_dump() == {
        "queued": 0,
        "in_progress": 0,
        "retryable": 0,
        "stranded": 0,
        "total_backlog": 0,
        "oldest_queued_at": None,
        "oldest_age_seconds": None,
        "sampled_at": int(now.timestamp()),
    }


def test_queue_endpoint_is_unavailable_before_initial_snapshot(engine: Engine) -> None:
    monitor = QueueMonitor(engine, job_timeout=120)

    with pytest.raises(HTTPException) as error:
        queue_status(monitor)

    assert error.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
