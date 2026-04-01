import datetime
from typing import cast

import pytest
from fastapi import HTTPException, status
from fastapi_pagination import Page
from letsbuilda.pypi import PyPIServices
from letsbuilda.pypi.exceptions import PackageNotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from mainframe.endpoints.job import get_jobs
from mainframe.endpoints.package import (
    _deduplicate_packages,  # pyright: ignore [reportPrivateUsage]
    batch_queue_package,
    lookup_package_info,
    lookup_reported_packages,
    queue_package,
    submit_results,
)
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan, Status
from mainframe.models.schemas import (
    Package,
    PackageScanResult,
    PackageScanResultFail,
    PackageSpecifier,
)
from mainframe.rules import Rules


@pytest.mark.parametrize(
    ("since", "name", "version", "page", "size"),
    [
        (0, "a", None, 1, 50),
        (0, None, None, 1, 50),
        (0, "b", None, 1, 50),
        (None, "a", "0.1.0", 1, 50),
        (0, "a", None, None, None),  # No pagination parameters
        (None, "a", "0.1.0", None, None),  # No pagination parameters
    ],
)
def test_package_lookup(  # noqa: PLR0913
    since: int | None,
    name: str | None,
    version: str | None,
    page: int | None,
    size: int | None,
    test_data: list[Scan],
    db_session: Session,
):
    expected_scans = {
        (scan.name, scan.version)
        for scan in test_data
        if (
            (since is None or (scan.finished_at and since <= int(scan.finished_at.timestamp())))
            and (name is None or scan.name == name)
            and (version is None or scan.version == version)
        )
    }

    actual_scans = lookup_package_info(db_session, since, name, version, page, size)

    if isinstance(actual_scans, Page):
        page_results = cast("Page[Package]", actual_scans)
        actual_scan_set = {(scan.name, scan.version) for scan in page_results.items}
    else:
        sequence_results = cast("list[Package]", actual_scans)
        actual_scan_set = {(scan.name, scan.version) for scan in sequence_results}

    assert expected_scans == actual_scan_set


@pytest.mark.parametrize(
    ("since", "name", "version"),
    [
        (0xC0FFEE, "name", "ver"),
        (0, None, "ver"),
        (None, None, "ver"),
        (None, None, None),
    ],
)
def test_package_lookup_rejects_invalid_combinations(
    db_session: Session,
    since: int | None,
    name: str | None,
    version: str | None,
):
    """Test that invalid combinations are rejected with a 400 response code."""
    with pytest.raises(HTTPException) as e:
        lookup_package_info(db_session, since, name, version)
    assert e.value.status_code == status.HTTP_400_BAD_REQUEST


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

        with db_session.begin():
            record = db_session.scalar(
                select(Scan).where(Scan.name == name).where(Scan.version == version).options(joinedload(Scan.rules))
            )

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
    db_session: Session,
    pypi_client: PyPIServices,
    auth: AuthenticationData,
    monkeypatch: pytest.MonkeyPatch,
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
    db_session: Session,
    pypi_client: PyPIServices,
    auth: AuthenticationData,
    monkeypatch: pytest.MonkeyPatch,
):
    # Make get_package_metadata always throw PackageNotFoundError to simulate an invalid package
    def _side_effect(name: str, version: str):
        raise PackageNotFoundError(name, version)

    monkeypatch.setattr(pypi_client, "get_package_metadata", _side_effect)

    package = PackageSpecifier(name="c", version="1.0.0")
    query = select(Scan).where(Scan.name == package.name).where(Scan.version == package.version)

    with pytest.raises(HTTPException) as e:
        queue_package(package, db_session, auth, pypi_client)
    assert e.value.status_code == status.HTTP_404_NOT_FOUND

    with db_session.begin():
        assert db_session.scalar(query) is None


def test_queue_duplicate_package(db_session: Session, pypi_client: PyPIServices, auth: AuthenticationData):
    package = PackageSpecifier(name="c", version="1.0.0")

    queue_package(package, db_session, auth, pypi_client)

    with pytest.raises(HTTPException) as e:
        queue_package(package, db_session, auth, pypi_client)
    assert e.value.status_code == status.HTTP_409_CONFLICT


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
    assert e.value.status_code == status.HTTP_404_NOT_FOUND


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
        assert e.value.status_code == status.HTTP_409_CONFLICT

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
        report_summary="reported for malware",
        queued_at=datetime.datetime(2024, 3, 5, 12, 30, 0, tzinfo=datetime.UTC),
    )

    pkg = Package.from_db(scan)

    assert pkg.name == "pyfoo"
    assert pkg.version == "3.12.2"
    assert pkg.score == 14
    assert pkg.queued_by == "Ryan"
    assert pkg.reported_by == "Ryan"
    assert pkg.report_summary == "reported for malware"
    assert pkg.queued_at == datetime.datetime(2024, 3, 5, 12, 30, 0, tzinfo=datetime.UTC)


def test_datetime_serialization():
    """Test that the datetime fields are serialized correctly."""
    scan = Scan(
        name="Pyfoo",
        version="3.13.0",
        status=Status.FINISHED,
        queued_at=datetime.datetime(2023, 10, 12, 13, 45, 30, tzinfo=datetime.UTC),
        pending_at=datetime.datetime(2023, 10, 12, 13, 45, 30, tzinfo=datetime.UTC),
        finished_at=datetime.datetime(2023, 10, 12, 13, 45, 30, tzinfo=datetime.UTC),
        reported_at=datetime.datetime(2023, 10, 12, 13, 45, 30, tzinfo=datetime.UTC),
        queued_by="Tina",
        report_summary="reported for malware",
    )

    pkg = Package.from_db(scan).model_dump()
    dt = int(datetime.datetime(2023, 10, 12, 13, 45, 30, tzinfo=datetime.UTC).timestamp())

    assert pkg.get("queued_at") == dt
    assert pkg.get("pending_at") == dt
    assert pkg.get("finished_at") == dt
    assert pkg.get("reported_at") == dt
    assert pkg.get("report_summary") == "reported for malware"


def test_reported_package_lookup_filters_orders_and_paginates(db_session: Session):
    earlier = datetime.datetime(2024, 1, 2, 12, 0, 0, tzinfo=datetime.UTC)
    later = datetime.datetime(2024, 1, 3, 12, 0, 0, tzinfo=datetime.UTC)

    scans = [
        Scan(
            name="alpha",
            version="1.0.0",
            status=Status.FINISHED,
            score=10,
            inspector_url="https://example.com/alpha",
            rules=[],
            download_urls=[],
            queued_at=earlier,
            queued_by="queue-user",
            pending_at=earlier,
            pending_by="pending-user",
            finished_at=earlier,
            finished_by="finished-user",
            reported_at=later,
            reported_by="reporter-2",
            report_summary="latest report",
            fail_reason=None,
            commit_hash="commit-2",
        ),
        Scan(
            name="alpha",
            version="0.9.0",
            status=Status.FINISHED,
            score=4,
            inspector_url="https://example.com/alpha-old",
            rules=[],
            download_urls=[],
            queued_at=earlier,
            queued_by="queue-user",
            pending_at=earlier,
            pending_by="pending-user",
            finished_at=earlier,
            finished_by="finished-user",
            reported_at=earlier,
            reported_by="reporter-1",
            report_summary="older report",
            fail_reason=None,
            commit_hash="commit-1",
        ),
        Scan(
            name="beta",
            version="2.0.0",
            status=Status.FINISHED,
            score=1,
            inspector_url="https://example.com/beta",
            rules=[],
            download_urls=[],
            queued_at=earlier,
            queued_by="queue-user",
            pending_at=earlier,
            pending_by="pending-user",
            finished_at=earlier,
            finished_by="finished-user",
            reported_at=None,
            reported_by=None,
            report_summary=None,
            fail_reason=None,
            commit_hash="commit-3",
        ),
    ]

    with db_session.begin():
        db_session.add_all(scans)

    page = lookup_reported_packages(
        db_session,
        since=int(datetime.datetime(2024, 1, 2, 0, 0, 0, tzinfo=datetime.UTC).timestamp()),
        name="alpha",
        page=1,
        size=1,
    )

    assert page.total == 2
    assert page.page == 1
    assert page.size == 1
    assert len(page.items) == 1
    assert page.items[0].name == "alpha"
    assert page.items[0].version == "1.0.0"
    assert page.items[0].reported_by == "reporter-2"
    assert page.items[0].report_summary == "latest report"

    second_page = lookup_reported_packages(
        db_session,
        since=int(datetime.datetime(2024, 1, 2, 0, 0, 0, tzinfo=datetime.UTC).timestamp()),
        name="alpha",
        page=2,
        size=1,
    )

    assert len(second_page.items) == 1
    assert second_page.items[0].version == "0.9.0"
    assert second_page.items[0].report_summary == "older report"
