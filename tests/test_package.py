from typing import Optional

import pytest
from letsbuilda.pypi import PyPIServices
from sqlalchemy import select
from sqlalchemy.orm import Session

from mainframe.endpoints.job import get_jobs
from mainframe.endpoints.package import (
    batch_queue_package,
    lookup_package_info,
    queue_package,
    submit_results,
)
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan, Status
from mainframe.models.schemas import PackageScanResultFail, PackageSpecifier
from mainframe.rules import Rules


@pytest.mark.parametrize(
    "since,name,version",
    [
        (0, "a", None),
        (0, None, None),
        (0, "b", None),
        (None, "a", "0.1.0"),
    ],
)
def test_package_lookup(
    since: Optional[int],
    name: Optional[str],
    version: Optional[str],
    test_data: list[Scan],
    db_session: Session,
):
    exp: set[tuple[str, str]] = set()
    for scan in test_data:
        if since is not None and (scan.finished_at is None or since > int(scan.finished_at.timestamp())):
            continue
        if name is not None and scan.name != name:
            continue
        if version is not None and scan.version != version:
            continue
        exp.add((scan.name, scan.version))

    scans = lookup_package_info(db_session, since, name, version)
    assert exp == {(scan.name, scan.version) for scan in scans}


def test_handle_fail(db_session: Session, test_data: list[Scan], auth: AuthenticationData, rules_state: Rules):
    job = get_jobs(db_session, auth, rules_state, batch=1)

    if job:
        job = job[0]
        name = job.name
        version = job.version
        reason = "Package too large"

        submit_results(PackageScanResultFail(name=name, version=version, reason=reason), db_session, auth)

        record = db_session.scalar(
            select(Scan)
            .where(Scan.name == name)
            .where(Scan.version == version)
            .where(Scan.status == Status.FAILED)
            .where(Scan.fail_reason == reason)
        )

        assert record is not None
    else:
        assert all(scan.status != Status.QUEUED for scan in test_data)


def test_batch_queue(db_session: Session, test_data: list[Scan], pypi_client: PyPIServices, auth: AuthenticationData):
    packages_to_add = [PackageSpecifier(name=scan.name, version=scan.version) for scan in test_data]
    packages_to_add.append(PackageSpecifier(name="c", version="1.0.0"))
    batch_queue_package(packages_to_add, db_session, auth, pypi_client)

    existing_packages = {(p.name, p.version) for p in db_session.scalars(select(Scan)).all()}
    for package in packages_to_add:
        assert (package.name, package.version) in existing_packages


def test_queue(db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData):
    package = PackageSpecifier(name="c", version="1.0.0")
    query = select(Scan).where(Scan.name == package.name).where(Scan.version == package.version)

    assert db_session.scalar(query) is None

    queue_package(package, db_session, auth, pypi_client)

    assert db_session.scalar(query) is not None
