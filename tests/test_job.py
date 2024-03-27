import datetime as dt

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from mainframe.endpoints.job import get_jobs
from mainframe.job_cache import JobCache
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan, Status
from mainframe.rules import Rules


def oldest_queued_package(db_session: Session):
    return db_session.scalar(select(func.min(Scan.queued_at)).where(Scan.status == Status.QUEUED))


def test_min_queue_date_of_queued_rows(test_data: list[Scan], db_session: Session):
    queued_at_times = [
        scan.queued_at for scan in test_data if scan.status is Status.QUEUED and scan.queued_at is not None
    ]
    if queued_at_times:
        assert min(queued_at_times) == oldest_queued_package(db_session)
    else:
        # no queued rows to get the min of
        pass


def fetch_queue_time(name: str, version: str, db_session: Session) -> dt.datetime | None:
    return db_session.scalar(select(Scan.queued_at).where(Scan.name == name).where(Scan.version == version))


def test_fetch_queue_time(test_data: list[Scan], db_session: Session):
    for scan in test_data:
        assert scan.queued_at == fetch_queue_time(scan.name, scan.version, db_session)


def test_job(
    test_data: list[Scan], db_session: Session, auth: AuthenticationData, rules_state: Rules, job_cache: JobCache
):
    job = get_jobs(job_cache, auth, rules_state, batch=1)
    if job:
        job = job[0]
        # if job, the row with the name and version we get should be pending
        # and the queued_at should be at least as old as all queued packages
        job_queued_at = fetch_queue_time(job.name, job.version, db_session)
        assert job_queued_at is not None
        oldest_still_queued = oldest_queued_package(db_session)
        assert oldest_still_queued is None or job_queued_at >= oldest_still_queued
    else:
        # if no job, there must be no queued packages
        assert all(scan.status != Status.QUEUED for scan in test_data)


def test_batch_job(db_session: Session, auth: AuthenticationData, rules_state: Rules, job_cache: JobCache):
    db_session.execute(update(Scan).values(status=Status.FINISHED))

    scans = [
        Scan(
            name=f"package{i}",
            version="1.0.0",
            status=Status.QUEUED,
            queued_by="remmy",
            queued_at=dt.datetime.now(dt.UTC),
        )
        for i in range(10)
    ]
    db_session.add_all(scans)
    db_session.commit()

    jobs = get_jobs(job_cache, auth, rules_state, 10)
    s = {(f"package{i}", "1.0.0") for i in range(10)}

    # check if each returned job should have actually been returned
    for job in jobs:
        assert (job.name, job.version) in s
