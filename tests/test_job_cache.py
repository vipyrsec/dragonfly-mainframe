import queue
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mainframe.constants import mainframe_settings
from mainframe.job_cache import JobCache
from mainframe.models.orm import Scan, Status
from mainframe.models.schemas import PackageScanResultFail


# Override globally defined job cache
@pytest.fixture
def job_cache(db_session: Session) -> JobCache:
    mock_sessionmaker = Mock(return_value=db_session)
    return JobCache(mock_sessionmaker, size=10)


def test_get_cached_job(job_cache: JobCache):
    scan = Scan(name="abc", version="1.0.0", status=Status.QUEUED)
    job_cache.scan_queue.put(scan)

    job = job_cache.get_job()
    assert job is not None
    assert job.name == "abc"
    assert job.version == "1.0.0"
    assert job.status == Status.PENDING


def test_from_queued_to_pending(job_cache: JobCache):
    scan = Scan(name="abc", version="1.0.0", status=Status.QUEUED)
    job_cache.scan_queue.put(scan)

    job_cache.get_job()
    assert job_cache.scan_queue.qsize() == 0
    assert [("abc", "1.0.0")] == [(s.name, s.version) for s in job_cache.pending]


def test_submit_result(job_cache: JobCache):
    scan = Scan(name="abc", version="1.0.0", status=Status.PENDING)
    job_cache.pending.append(scan)

    # let's just use fail here because it's less fields
    result = PackageScanResultFail(name="abc", version="1.0.0", reason="uwu")

    job_cache.submit_result(result)
    result = job_cache.results_queue.get_nowait()
    assert isinstance(result, PackageScanResultFail)
    assert result.name == "abc"
    assert result.version == "1.0.0"
    assert result.reason == "uwu"


def test_from_pending_to_finished(job_cache: JobCache):
    scan = Scan(name="abc", version="1.0.0", status=Status.PENDING)
    job_cache.pending.append(scan)

    # let's just use fail here because it's less fields
    result = PackageScanResultFail(name="abc", version="1.0.0", reason="uwu")

    job_cache.submit_result(result)

    # check that it's not in the pending queue
    assert [("abc", "1.0.0")] not in [(s.name, s.version) for s in job_cache.pending]


def test_refill(job_cache: JobCache, db_session: Session):
    queued = db_session.scalars(select(Scan).where(Scan.status == Status.QUEUED)).all()

    job_cache.refill()
    cached_queued: list[Scan] = []
    while True:
        try:
            cached_queued.append(job_cache.scan_queue.get_nowait())
        except queue.Empty:
            break

    assert [(s.name, s.version) for s in queued] == [(s.name, s.version) for s in cached_queued]


def test_requeue_timeouts(job_cache: JobCache):
    scan = Scan(
        name="abc",
        version="1.0.0",
        status=Status.PENDING,
        pending_at=datetime.now(UTC) - timedelta(seconds=mainframe_settings.job_timeout + 60),
    )

    job_cache.pending.append(scan)

    job_cache.requeue_timeouts()

    scan = job_cache.scan_queue.get_nowait()
    assert scan.name == "abc"
    assert scan.version == "1.0.0"
    assert scan.status == Status.QUEUED


def test_overfetch(job_cache: JobCache, db_session: Session):
    cache_size = job_cache.scan_queue.maxsize
    for i in range(cache_size - 1):
        pending_at = datetime.now(UTC) - timedelta(seconds=mainframe_settings.job_timeout + 60)
        scan = Scan(name=f"package-{i}", version="1.0.0", status=Status.PENDING, pending_at=pending_at)
        job_cache.pending.append(scan)

    db_session.execute(update(Scan).values(status=Status.FAILED))

    scan1 = Scan(
        name="abc",
        version="1.0.0",
        status=Status.QUEUED,
        queued_at=datetime.now(UTC) - timedelta(seconds=5),
        queued_by="remmy",
    )

    scan2 = Scan(
        name="def",
        version="1.0.0",
        status=Status.QUEUED,
        queued_at=datetime.now(UTC),
        queued_by="remmy",
    )

    db_session.add_all((scan1, scan2))
    db_session.commit()

    job_cache.refill()

    cached_queued: list[str] = []
    while True:
        try:
            scan = job_cache.scan_queue.get_nowait()
            cached_queued.append(scan.name)
        except queue.Empty:
            break

    assert cached_queued == [f"package-{i}" for i in range(cache_size - 1)] + ["abc"]
