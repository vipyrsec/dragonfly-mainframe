from copy import deepcopy
from datetime import datetime, timedelta
from typing import Optional
import pytest
from sqlalchemy import select
from mainframe.database import DatabaseStorage
from mainframe.models.orm import Scan, Status


@pytest.mark.db
def test_mark_reported(storage: DatabaseStorage):
    scan = Scan(
        name="package1",
        version="1.0.0",
        status=Status.FINISHED,
        queued_by="remmy",
        queued_at=datetime.now(),
    )

    session = storage.get_session()
    with session.begin():
        session.add(scan)

        storage.mark_reported(scan=scan, subject="remmy")

        query = select(Scan).where(Scan.name == "package1").where(Scan.version == "1.0.0")
        actual = session.scalar(query)
        assert actual is not None
        assert actual.reported_by == "remmy"
        assert actual.reported_at is not None


@pytest.mark.db
@pytest.mark.parametrize(
    "scans,spec,expected",
    [
        (
            [Scan(name="package1", version="1.0.0", status=Status.QUEUED, queued_by="remmy", queued_at=datetime.now())],
            ("package1", None, None),
            [("package1", "1.0.0")],
        ),
        (
            [Scan(name="package1", version="1.0.0", status=Status.QUEUED, queued_by="remmy", queued_at=datetime.now())],
            ("package1", "1.0.0", None),
            [("package1", "1.0.0")],
        ),
        (
            [
                Scan(
                    name="package1", version="1.0.0", status=Status.QUEUED, queued_by="remmy", queued_at=datetime.now()
                ),
                Scan(
                    name="package1", version="1.0.1", status=Status.QUEUED, queued_by="remmy", queued_at=datetime.now()
                ),
            ],
            ("package1", None, None),
            [("package1", "1.0.0"), ("package1", "1.0.1")],
        ),
        (
            [
                Scan(
                    name="package1", version="1.0.0", status=Status.QUEUED, queued_by="remmy", queued_at=datetime.now()
                ),
                Scan(
                    name="package1", version="1.0.1", status=Status.QUEUED, queued_by="remmy", queued_at=datetime.now()
                ),
            ],
            ("package1", "1.0.1", None),
            [("package1", "1.0.1")],
        ),
        (
            [
                Scan(
                    name="package1",
                    version="1.0.0",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=5),
                ),
                Scan(
                    name="package1",
                    version="1.0.1",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=2),
                ),
            ],
            ("package1", None, 0),
            [("package1", "1.0.0"), ("package1", "1.0.1")],
        ),
        (
            [
                Scan(
                    name="package1",
                    version="1.0.0",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=5),
                ),
                Scan(
                    name="package1",
                    version="1.0.1",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=2),
                ),
            ],
            ("package1", None, datetime.now() - timedelta(seconds=4)),
            [("package1", "1.0.1")],
        ),
        # we must use a static time for this test here because it can be flaky otherwise
        (
            [
                Scan(
                    name="package1",
                    version="1.0.0",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime(2024, 10, 4, 2, 4) - timedelta(seconds=5),
                ),
                Scan(
                    name="package1",
                    version="1.0.1",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime(2024, 10, 4, 2, 4) - timedelta(seconds=2),
                ),
            ],
            ("package1", None, datetime(2024, 10, 4, 2, 4) - timedelta(seconds=2)),
            [("package1", "1.0.1")],
        ),
        (
            [
                Scan(
                    name="package1",
                    version="1.0.0",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=5),
                ),
                Scan(
                    name="package1",
                    version="1.0.1",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=2),
                ),
            ],
            ("package1", "1.0.0", datetime.now() - timedelta(seconds=2)),
            [],
        ),
        (
            [
                Scan(
                    name="package1",
                    version="1.0.0",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=5),
                ),
                Scan(
                    name="package1",
                    version="1.0.1",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=2),
                ),
            ],
            ("package1", None, datetime.now() - timedelta(seconds=1)),
            [],
        ),
        (
            [
                Scan(
                    name="package1",
                    version="1.0.0",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=5),
                ),
                Scan(
                    name="package1",
                    version="1.0.1",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=2),
                ),
            ],
            ("package2", None, None),
            [],
        ),
        (
            [
                Scan(
                    name="package1",
                    version="1.0.0",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=5),
                ),
                Scan(
                    name="package1",
                    version="1.0.1",
                    status=Status.FINISHED,
                    queued_by="remmy",
                    queued_at=datetime.now() - timedelta(seconds=10),
                    finished_at=datetime.now() - timedelta(seconds=2),
                ),
            ],
            ("package1", "1.0.2", None),
            [],
        ),
    ],
)
def test_lookup_packages(
    storage: DatabaseStorage,
    scans: list[Scan],
    spec: tuple[Optional[str], Optional[str], Optional[datetime]],
    expected: list[tuple[str, str]],
):
    session = storage.get_session()
    with session, session.begin():
        session.add_all(deepcopy(scans))

    name, version, since = spec
    results = storage.lookup_packages(name=name, version=version, since=since)

    assert sorted((s.name, s.version) for s in results) == sorted(expected)
