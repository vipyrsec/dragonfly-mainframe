from typing import Optional

import pytest
from fastapi import HTTPException
from letsbuilda.pypi import PyPIServices
from letsbuilda.pypi.exceptions import PackageNotFoundError
from pytest import MonkeyPatch
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
from mainframe.models.schemas import (
    PackageScanResult,
    PackageScanResultFail,
    PackageSpecifier,
)
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


@pytest.mark.parametrize(
    "since,name,version",
    [
        (0xC0FFEE, "name", "ver"),
        (0, None, "ver"),
        (None, None, "ver"),
        (None, None, None),
    ],
)
def test_package_lookup_rejects_invalid_combinations(
    db_session: Session,
    since: Optional[int],
    name: Optional[str],
    version: Optional[str],
):
    """Test that invalid combinations are rejected with a 400 response code."""

    with pytest.raises(HTTPException) as e:
        lookup_package_info(db_session, since, name, version)
    assert e.value.status_code == 400


def test_handle_success(db_session: Session, test_data: list[Scan], auth: AuthenticationData, rules_state: Rules):
    job = get_jobs(db_session, auth, rules_state, batch=1)

    if job:
        job = job[0]
        name = job.name
        version = job.version

        body = PackageScanResult(
            name=job.name,
            version=job.version,
            commit=rules_state.rules_commit,
            score=2,
            inspector_url="test inspector url",
            rules_matched=["a", "b", "c"],
        )
        submit_results(body, db_session, auth)

        record = db_session.scalar(select(Scan).where(Scan.name == name).where(Scan.version == version))

        assert record is not None
        assert record.score == 2
        assert record.inspector_url == "test inspector url"
        assert {rule.name for rule in record.rules} == {"a", "b", "c"}
    else:
        assert all(scan.status != Status.QUEUED for scan in test_data)


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


def test_batch_queue_nonexistent_package(
    db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData, monkeypatch: MonkeyPatch
):
    # Make get_package_metadata always throw PackageNotFoundError to simulate an invalid package
    def _side_effect(name: str, version: str):
        raise PackageNotFoundError(name, version)

    monkeypatch.setattr(pypi_client, "get_package_metadata", _side_effect)

    package_to_add = PackageSpecifier(name="c", version="1.0.0")
    batch_queue_package([package_to_add], db_session, auth, pypi_client)

    existing_packages = {(p.name, p.version) for p in db_session.scalars(select(Scan)).all()}
    assert ("c", "1.0.0") not in existing_packages


def test_queue(db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData):
    package = PackageSpecifier(name="c", version="1.0.0")
    query = select(Scan).where(Scan.name == package.name).where(Scan.version == package.version)

    assert db_session.scalar(query) is None

    queue_package(package, db_session, auth, pypi_client)

    assert db_session.scalar(query) is not None


def test_queue_nonexistent_package(
    db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData, monkeypatch: MonkeyPatch
):
    # Make get_package_metadata always throw PackageNotFoundError to simulate an invalid package
    def _side_effect(name: str, version: str):
        raise PackageNotFoundError(name, version)

    monkeypatch.setattr(pypi_client, "get_package_metadata", _side_effect)

    package = PackageSpecifier(name="c", version="1.0.0")
    query = select(Scan).where(Scan.name == package.name).where(Scan.version == package.version)

    with pytest.raises(HTTPException) as e:
        queue_package(package, db_session, auth, pypi_client)
    assert e.value.status_code == 404

    assert db_session.scalar(query) is None


def test_queue_duplicate_package(db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData):
    package = PackageSpecifier(name="c", version="1.0.0")

    queue_package(package, db_session, auth, pypi_client)

    with pytest.raises(HTTPException) as e:
        queue_package(package, db_session, auth, pypi_client)
    assert e.value.status_code == 409


def test_submit_nonexistent_package(db_session: Session, auth: AuthenticationData):
    body = PackageScanResult(
        name="c",
        version="1.0.0",
        commit="test rules commit",
        score=2,
        inspector_url="test inspector url",
        rules_matched=["a", "b", "c"],
    )

    with pytest.raises(HTTPException) as e:
        submit_results(body, db_session, auth)
    assert e.value.status_code == 404


def test_submit_duplicate_package(
    db_session: Session, test_data: list[Scan], auth: AuthenticationData, rules_state: Rules
):
    job = get_jobs(db_session, auth, rules_state, batch=1)

    if job:
        job = job[0]

        body = PackageScanResult(
            name=job.name,
            version=job.version,
            commit=rules_state.rules_commit,
            score=2,
            inspector_url="test inspector url",
            rules_matched=["a", "b", "c"],
        )
        submit_results(body, db_session, auth)

        with pytest.raises(HTTPException) as e:
            submit_results(body, db_session, auth)
        assert e.value.status_code == 409

    else:
        assert all(scan.status != Status.QUEUED for scan in test_data)
