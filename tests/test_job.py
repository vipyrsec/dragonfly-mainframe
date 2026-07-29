import datetime as dt

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from mainframe.endpoints.job import get_jobs
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan, Status
from mainframe.rules import Rules


def oldest_queued_package(db_session: Session):
    with db_session.begin():
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
    with db_session.begin():
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
        assert job_queued_at is not None
        oldest_still_queued = oldest_queued_package(db_session)
        assert oldest_still_queued is None or job_queued_at >= oldest_still_queued
    else:
        # if no job, there must be no queued packages
        assert all(scan.status != Status.QUEUED for scan in test_data)


def test_batch_job(test_data: list[Scan], db_session: Session, auth: AuthenticationData, rules_state: Rules):
    jobs = {(job.name, job.version) for job in get_jobs(db_session, auth, rules_state, batch=len(test_data))}

    # check if each returned job should have actually been returned
    for row in test_data:
        if row.status == Status.QUEUED:
            assert (row.name, row.version) in jobs
        elif row.status == Status.PENDING:
            assert row.pending_at is not None  # Appease the type checker
            if dt.datetime.now(dt.UTC) - row.pending_at > dt.timedelta(minutes=2):
                assert (row.name, row.version) in jobs
        else:
            assert (row.name, row.version) not in jobs

    # check if the database was accurately updated
    with db_session.begin():
        for name, version in jobs:
            row = db_session.scalar(select(Scan).where(Scan.name == name).where(Scan.version == version))

            assert row is not None
            assert row.status == Status.PENDING
            assert row.pending_by is not None
            assert row.pending_at is not None
            assert row.attempt_count == 1


def test_expired_scan_gets_a_final_attempt_then_is_dead_lettered(
    db_session: Session,
    auth: AuthenticationData,
    rules_state: Rules,
) -> None:
    now = dt.datetime.now(dt.UTC)
    poison = Scan(
        name="poison",
        version="1",
        status=Status.PENDING,
        queued_at=now - dt.timedelta(minutes=10),
        queued_by="test",
        pending_at=now - dt.timedelta(minutes=3),
        pending_by="previous-worker",
        attempt_count=2,
    )
    with db_session.begin():
        db_session.execute(update(Scan).values(status=Status.FINISHED))
        db_session.add(poison)

    jobs = get_jobs(db_session, auth, rules_state)

    assert [(job.name, job.version) for job in jobs] == [("poison", "1")]
    assert jobs[0].attempt == 3
    with db_session.begin():
        row = db_session.scalar(select(Scan).where(Scan.name == "poison"))
        assert row is not None
        assert row.status == Status.PENDING
        assert row.attempt_count == 3
        assert row.dead_lettered_at is None
        row.pending_at = now - dt.timedelta(minutes=3)

    jobs = get_jobs(db_session, auth, rules_state)

    assert jobs == []
    with db_session.begin():
        row = db_session.scalar(select(Scan).where(Scan.name == "poison"))
        assert row is not None
        assert row.status == Status.FAILED
        assert row.attempt_count == 3
        assert row.dead_lettered_at is not None
        assert row.fail_reason == "Worker lease expired after 3 scan attempts"


def test_dead_lettering_does_not_block_healthy_work(
    db_session: Session,
    auth: AuthenticationData,
    rules_state: Rules,
) -> None:
    now = dt.datetime.now(dt.UTC)
    with db_session.begin():
        db_session.execute(update(Scan).values(status=Status.FINISHED))
        db_session.add_all(
            [
                Scan(
                    name="exhausted",
                    version="1",
                    status=Status.PENDING,
                    queued_at=now - dt.timedelta(minutes=10),
                    queued_by="test",
                    pending_at=now - dt.timedelta(minutes=3),
                    pending_by="previous-worker",
                    attempt_count=3,
                ),
                Scan(
                    name="healthy",
                    version="1",
                    status=Status.QUEUED,
                    queued_at=now - dt.timedelta(minutes=1),
                    queued_by="test",
                ),
            ]
        )

    jobs = get_jobs(db_session, auth, rules_state)

    assert [(job.name, job.version) for job in jobs] == [("healthy", "1")]
    with db_session.begin():
        rows = {
            scan.name: scan for scan in db_session.scalars(select(Scan).where(Scan.name.in_(["exhausted", "healthy"])))
        }
        assert rows["exhausted"].status == Status.FAILED
        assert rows["exhausted"].dead_lettered_at is not None
        assert rows["healthy"].status == Status.PENDING
        assert rows["healthy"].attempt_count == 1
