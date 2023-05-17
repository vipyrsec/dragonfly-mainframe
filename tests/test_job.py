import uuid

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mainframe.models.orm import Package, Status


def test_job(api_url: str, test_data: list[dict], db_session: Session):
    r = requests.post(f"{api_url}/job")
    r.raise_for_status()
    j = r.json()
    if "package_id" in j:
        # if job, the row with the name and version we get should be pending
        # and the queued_at should be at least as old as all queued packages
        pid, job_queued_at = db_session.execute(
            select(Package.package_id, Package.queued_at).where(
                (Package.name == j["name"]) & (Package.version == j["version"])
            )
        ).first()  # type: ignore
        oldest_still_queued = db_session.scalar(
            select(func.min(Package.queued_at)).where(Package.status == Status.QUEUED)
        )
        assert uuid.UUID(f"{{{j['package_id']}}}") == pid and (
            oldest_still_queued is None or job_queued_at >= oldest_still_queued
        )
    else:
        # if no job, there must be no queued packages
        assert all(d["status"] != "queued" for d in test_data)
