from typing import Optional
import datetime

import pytest
from fastapi import HTTPException
from letsbuilda.pypi import PyPIServices
from letsbuilda.pypi.exceptions import PackageNotFoundError
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from mainframe.endpoints.job import get_jobs
from mainframe.endpoints.package import _deduplicate_packages  # pyright: ignore [reportPrivateUsage]
from mainframe.endpoints.package import (
    batch_queue_package,
    lookup_package_info,
    queue_package,
    submit_results,
)
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan, Status
from mainframe.models.schemas import (
    File,
    Files,
    Match,
    Package,
    PackageScanResult,
    PackageScanResultFail,
    PackageSpecifier,
    PatternMatch,
    Range,
    RuleMatch,
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


def test_package_lookup_files(db_session: Session):
    """Test that `lookup_package_info` returns detailed file information."""

    range_ = Range(start=0, end=5)
    match = Match(range=range_, data=[0xDE, 0xAD, 0xBE, 0xEF])
    pattern = PatternMatch(identifier="$pat", matches=[match])
    rule = RuleMatch(identifier="rule1", patterns=[pattern], metadata={"author": "remmy", "score": 5})
    file = File(path="dist1/a/b.py", matches=[rule])
    files = Files([file])
    scan = Scan(
        name="abc",
        version="1.0.0",
        status=Status.FINISHED,
        queued_by="remmy",
        files=files,
    )

    with db_session.begin():
        db_session.add(scan)
        db_session.commit()

    package = lookup_package_info(db_session, name="abc", version="1.0.0")[0]

    assert package.files == files


def test_handle_success(db_session: Session, test_data: list[Scan], auth: AuthenticationData, rules_state: Rules):
    job = get_jobs(db_session, auth, rules_state, batch=1)

    if job:
        job = job[0]
        name = job.name
        version = job.version

        range_ = Range(start=0, end=5)
        match = Match(range=range_, data=[0xDE, 0xAD, 0xBE, 0xEF])
        pattern = PatternMatch(identifier="$pat", matches=[match])
        rule = RuleMatch(identifier="rule1", patterns=[pattern], metadata={"author": "remmy", "score": 5})
        file = File(path="dist1/a/b.py", matches=[rule])
        files = Files([file])

        body = PackageScanResult(
            name=job.name,
            version=job.version,
            commit=rules_state.rules_commit,
            score=2,
            inspector_url="test inspector url",
            rules_matched=["a", "b", "c"],
            files=files,
        )
        submit_results(body, db_session, auth)

        with db_session.begin():
            record = db_session.scalar(
                select(Scan).where(Scan.name == name).where(Scan.version == version).options(joinedload(Scan.rules))
            )

        assert record is not None
        assert record.score == 2
        assert record.inspector_url == "test inspector url"
        assert {rule.name for rule in record.rules} == {"a", "b", "c"}
        assert record.files == files
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

        with db_session.begin():
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


def test_batch_queue(db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData):
    pack = PackageSpecifier(name="c", version="1.0.0")
    batch_queue_package([pack], db_session, auth, pypi_client)

    with db_session.begin():
        existing_packages = {(p.name, p.version) for p in db_session.scalars(select(Scan))}
    assert (pack.name, pack.version) in existing_packages


def test_batch_queue_empty_packages(db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData):
    with db_session.begin():
        before = sorted((s.name, s.version) for s in db_session.scalars(select(Scan)))
    batch_queue_package([], db_session, auth, pypi_client)
    with db_session.begin():
        after = sorted((s.name, s.version) for s in db_session.scalars(select(Scan)))
    assert before == after


@pytest.mark.parametrize("packages", [[PackageSpecifier(name="c", version="1.0.0")], []])
def test_deduplicate_packages(test_data: list[Scan], packages: list[PackageSpecifier], db_session: Session):
    non_unique = [PackageSpecifier(name=scan.name, version=scan.version) for scan in test_data]

    with db_session.begin():
        result = _deduplicate_packages(non_unique + packages, db_session)

    assert sorted(result) == sorted((p.name, p.version) for p in packages)


def test_batch_queue_nonexistent_package(
    db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData, monkeypatch: MonkeyPatch
):
    # Make get_package_metadata always throw PackageNotFoundError to simulate an invalid package
    def _side_effect(name: str, version: str):
        raise PackageNotFoundError(name, version)

    monkeypatch.setattr(pypi_client, "get_package_metadata", _side_effect)

    package_to_add = PackageSpecifier(name="c", version="1.0.0")
    batch_queue_package([package_to_add], db_session, auth, pypi_client)

    with db_session.begin():
        existing_packages = {(p.name, p.version) for p in db_session.scalars(select(Scan)).all()}
    assert ("c", "1.0.0") not in existing_packages


def test_queue(db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData):
    package = PackageSpecifier(name="c", version="1.0.0")
    query = select(Scan).where(Scan.name == package.name).where(Scan.version == package.version)

    with db_session.begin():
        assert db_session.scalar(query) is None

    queue_package(package, db_session, auth, pypi_client)

    with db_session.begin():
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

    with db_session.begin():
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


def test_package_from_db():
    scan = Scan(
        name="pyfoo",
        version="3.12.2",
        status=Status.FINISHED,
        score=14,
        queued_by="Ryan",
        reported_by="Ryan",
        queued_at=datetime.datetime(2024, 3, 5, 12, 30, 0),
    )

    pkg = Package.from_db(scan)

    assert pkg.name == "pyfoo"
    assert pkg.version == "3.12.2"
    assert pkg.score == 14
    assert pkg.queued_by == "Ryan"
    assert pkg.reported_by == "Ryan"
    assert pkg.queued_at == datetime.datetime(2024, 3, 5, 12, 30, 0)


def test_datetime_serialization():
    """Test that the datetime fields are serialized correctly."""

    scan = Scan(
        name="Pyfoo",
        version="3.13.0",
        status=Status.FINISHED,
        queued_at=datetime.datetime(2023, 10, 12, 13, 45, 30),
        pending_at=datetime.datetime(2023, 10, 12, 13, 45, 30),
        finished_at=datetime.datetime(2023, 10, 12, 13, 45, 30),
        reported_at=datetime.datetime(2023, 10, 12, 13, 45, 30),
        queued_by="Tina",
    )

    pkg = Package.from_db(scan).model_dump()
    dt = int(datetime.datetime(2023, 10, 12, 13, 45, 30).timestamp())

    assert pkg.get("queued_at") == dt
    assert pkg.get("pending_at") == dt
    assert pkg.get("finished_at") == dt
    assert pkg.get("reported_at") == dt
