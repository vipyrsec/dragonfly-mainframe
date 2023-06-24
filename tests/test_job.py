import datetime as dt
import typing
import uuid

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mainframe.models.orm import Scan, Status


def oldest_queued_package(db_session: Session):
    return db_session.scalar(select(func.min(Scan.queued_at)).where(Scan.status == Status.QUEUED))


def test_min_queue_date_of_queued_rows(test_data: list[dict], db_session: Session):
    t = list(d["queued_at"] for d in test_data if d["status"] is Status.QUEUED)
    if t:
        assert min(t) == oldest_queued_package(db_session)
    else:
        # no queued rows to get the min of
        pass


def fetch_pid_and_queue_time(name: str, version: str, db_session: Session) -> tuple[uuid.UUID, dt.datetime]:
    t = db_session.execute(
        select(Scan.scan_id, Scan.queued_at).where((Scan.name == name) & (Scan.version == version))
    ).first()
    return typing.cast(tuple[uuid.UUID, dt.datetime], t)


def test_fetch_pid_and_queue_time(test_data: list[dict], db_session: Session):
    for d in test_data:
        assert (d["package_id"], d["queued_at"]) == fetch_pid_and_queue_time(d["name"], d["version"], db_session)


def test_job(api_url: str, test_data: list[dict], db_session: Session):
    r = requests.post(f"{api_url}/job")
    r.raise_for_status()
    j = r.json()
    if "package_id" in j:
        # if job, the row with the name and version we get should be pending
        # and the queued_at should be at least as old as all queued packages
        pid, job_queued_at = fetch_pid_and_queue_time(j["name"], j["version"], db_session)
        oldest_still_queued = oldest_queued_package(db_session)
        assert uuid.UUID(f"{{{j['package_id']}}}") == pid and (
            oldest_still_queued is None or job_queued_at >= oldest_still_queued
        )
    else:
        # if no job, there must be no queued packages
        assert all(d["status"] != "queued" for d in test_data)
