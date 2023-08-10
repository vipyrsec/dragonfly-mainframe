import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mainframe.endpoints.job import get_jobs
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


def test_job(test_data: list[Scan], db_session: Session, auth: AuthenticationData, rules_state: Rules):
    job = get_jobs(db_session, auth, rules_state, batch=1)
    if job:
        job = job[0]
        # if job, the row with the name and version we get should be pending
        # and the queued_at should be at least as old as all queued packages
        job_queued_at = fetch_queue_time(job.name, job.version, db_session)
        oldest_still_queued = oldest_queued_package(db_session)
        assert oldest_still_queued is None or job_queued_at >= oldest_still_queued
    else:
        # if no job, there must be no queued packages
        assert all(scan.status != Status.QUEUED for scan in test_data)


def test_batch_job(test_data: list[Scan], db_session: Session, auth: AuthenticationData, rules_state: Rules):
    jobs = get_jobs(db_session, auth, rules_state, batch=len(test_data))

    # check if each returned job should have actually been returned
    for job in jobs:
        original_data = next(scan for scan in test_data if (scan.name, scan.version) == (job.name, job.version))
        if original_data.status == Status.QUEUED:
            assert True
        elif original_data.status == Status.PENDING:
            assert original_data.pending_at is not None  # Appease the typechecker
            assert dt.datetime.now(tz=dt.timezone.utc) - original_data.pending_at > dt.timedelta(minutes=2)
        else:
            assert False

    # check if the database was accurately updated
    for job in jobs:
        row = db_session.scalar(select(Scan).where(Scan.name == job.name).where(Scan.version == job.version))

        assert row is not None
        assert row.status == Status.PENDING
        assert row.pending_by is not None
        assert row.pending_at is not None
