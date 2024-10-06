from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from mainframe.custom_exceptions import PackageAlreadyReported, PackageNotFound
from mainframe.endpoints.report import (
    validate_package,
    get_reported_version,
)
from mainframe.endpoints.report import (
    _validate_additional_information,  # pyright: ignore [reportPrivateUsage]
)
from mainframe.endpoints.report import (
    _validate_inspector_url,  # pyright: ignore [reportPrivateUsage]
)
from mainframe.endpoints.report import (
    _validate_pypi,  # pyright: ignore [reportPrivateUsage]
)
from mainframe.endpoints.report import report_package
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import DownloadURL, Rule, Scan, Status
from mainframe.models.schemas import (
    ObservationKind,
    ObservationReport,
    ReportPackageBody,
)
from tests.conftest import MockDatabase


def test_get_reported_version():
    scan1 = Scan(
        name="package1",
        version="1.0.0",
        reported_at=datetime.now(),
    )

    scan2 = Scan(
        name="package1",
        version="1.0.1",
        reported_at=None,
    )

    scans = [scan1, scan2]

    assert get_reported_version(scans) == scan1


def test_get_no_reported_version():
    scan1 = Scan(
        name="package1",
        version="1.0.0",
        reported_at=None,
    )

    scan2 = Scan(
        name="package1",
        version="1.0.1",
        reported_at=None,
    )

    scans = [scan1, scan2]

    assert get_reported_version(scans) is None


def test_validate_package():
    scan1 = Scan(
        name="package1",
        version="1.0.0",
        status=Status.FINISHED,
        queued_by="remmy",
        queued_at=datetime.now(),
        reported_at=None,
    )

    assert validate_package("package1", "1.0.0", [scan1]) == scan1


def test_validate_package_not_found():
    scan1 = Scan(
        name="package1",
        version="1.0.0",
        status=Status.FINISHED,
        queued_by="remmy",
        queued_at=datetime.now(),
        reported_at=None,
    )

    with pytest.raises(PackageNotFound):
        validate_package("package2", "1.0.0", [scan1])


def test_validate_package_already_reported():
    scan1 = Scan(
        name="package1",
        version="1.0.0",
        status=Status.FINISHED,
        queued_by="remmy",
        queued_at=datetime.now(),
        reported_at=None,
    )
    scan2 = Scan(
        name="package1",
        version="1.0.1",
        status=Status.FINISHED,
        queued_by="remmy",
        queued_at=datetime.now(),
        reported_at=datetime.now(),
    )

    with pytest.raises(PackageAlreadyReported) as e:
        validate_package("package1", "1.0.0", [scan1, scan2])

    assert (e.value.name, e.value.reported_version) == ("package1", "1.0.1")


def test_report_package_not_on_pypi():
    mock_httpx_client = MagicMock(spec=httpx.Client)
    mock_httpx_client.configure_mock(**{"get.return_value.status_code": 404})

    with pytest.raises(HTTPException) as e:
        _validate_pypi("c", "1.0.0", mock_httpx_client)

    assert e.value.status_code == 404

def test_report_package_not_found(auth: AuthenticationData, mock_database: MockDatabase):
    body = ReportPackageBody(
        name="this-package-does-not-exist",
        version="1.0.0",
        recipient=None,
        inspector_url=None,
        additional_information="this package is bad",
    )

    with pytest.raises(HTTPException) as e:
        report_package(body, mock_database, auth, MagicMock())

    assert e.value.status_code == 404
def test_report(auth: AuthenticationData, mock_database: MockDatabase):
    scan = Scan(
        name="c",
        version="1.0.0",
        status=Status.FINISHED,
        score=10,
        inspector_url="test inspector url",
        rules=[Rule(name="rule 1"), Rule(name="rule 2")],
        download_urls=[DownloadURL(url="test download url")],
        queued_at=datetime.now() - timedelta(seconds=60),
        queued_by="remmy",
        pending_at=datetime.now() - timedelta(seconds=30),
        pending_by="remmy",
        finished_at=datetime.now(),
        finished_by="remmy",
        reported_at=None,
        reported_by=None,
        fail_reason=None,
        commit_hash="test commit hash",
    )

    mock_database.add(scan)

    body = ReportPackageBody(
        name="c",
        version="1.0.0",
        recipient=None,
        inspector_url=None,
        additional_information="this package is bad",
    )

    expected = ObservationReport(
        kind=ObservationKind.Malware,
        summary="this package is bad",
        inspector_url="test inspector url",
        extra=dict(yara_rules=["rule 1", "rule 2"]),
    )

    mock_httpx_client = MagicMock()

    report_package(body, mock_database, auth, mock_httpx_client)

    mock_httpx_client.post.assert_called_once_with("/report/c", json=jsonable_encoder(expected))

    assert scan.reported_by is auth.subject
    assert scan.reported_at is not None


def test_report_missing_inspector_url():
    with pytest.raises(HTTPException) as e:
        _validate_inspector_url("a", "1.0.0", None, None)
    assert e.value.status_code == 400


@pytest.mark.parametrize(
    ("body_url", "scan_url"),
    [
        ("test url", None),
        (None, "test url"),
    ],
)
def test_report_inspector_url(body_url: Optional[str], scan_url: Optional[str]):
    assert "test url" == _validate_inspector_url("a", "1.0.0", body_url, scan_url)


@pytest.mark.parametrize(
    ("body", "scan"),
    [
        (  # No additional information, and no rules with email
            ReportPackageBody(
                name="c",
                version="1.0.0",
                recipient=None,
                inspector_url="inspector url override",
                additional_information=None,
                use_email=True,
            ),
            Scan(
                name="c",
                version="1.0.0",
                status=Status.FINISHED,
                score=0,
                inspector_url=None,
                rules=[],
                download_urls=[],
                queued_at=datetime.now() - timedelta(seconds=60),
                queued_by="remmy",
                pending_at=datetime.now() - timedelta(seconds=30),
                pending_by="remmy",
                finished_at=datetime.now() - timedelta(seconds=10),
                finished_by="remmy",
                reported_at=None,
                reported_by=None,
                fail_reason=None,
                commit_hash="test commit hash",
            ),
        ),
        (  # No additional information with Observations
            ReportPackageBody(
                name="c",
                version="1.0.0",
                recipient=None,
                inspector_url="inspector url override",
                additional_information=None,
                use_email=False,
            ),
            Scan(
                name="c",
                version="1.0.0",
                status=Status.FINISHED,
                score=0,
                inspector_url=None,
                rules=[Rule(name="ayo")],
                download_urls=[],
                queued_at=datetime.now() - timedelta(seconds=60),
                queued_by="remmy",
                pending_at=datetime.now() - timedelta(seconds=30),
                pending_by="remmy",
                finished_at=datetime.now() - timedelta(seconds=10),
                finished_by="remmy",
                reported_at=None,
                reported_by=None,
                fail_reason=None,
                commit_hash="test commit hash",
            ),
        ),
    ],
)
def test_report_missing_additional_information(body: ReportPackageBody, scan: Scan):
    with pytest.raises(HTTPException) as e:
        _validate_additional_information(body, scan)
    assert e.value.status_code == 400


@pytest.mark.parametrize(
    ("scans", "name", "version", "expected_exception"),
    [
        ([], "a", "1.0.0", PackageNotFound),
        (
            [
                Scan(
                    name="c",
                    version="1.0.0",
                    status=Status.FINISHED,
                    score=0,
                    inspector_url=None,
                    rules=[],
                    download_urls=[],
                    queued_at=datetime.now() - timedelta(seconds=60),
                    queued_by="remmy",
                    pending_at=datetime.now() - timedelta(seconds=30),
                    pending_by="remmy",
                    finished_at=datetime.now() - timedelta(seconds=10),
                    finished_by="remmy",
                    reported_at=datetime.now() - timedelta(days=1),
                    reported_by="jason",
                    fail_reason=None,
                    commit_hash="test commit hash",
                ),
                Scan(
                    name="c",
                    version="1.0.1",
                    status=Status.FINISHED,
                    score=0,
                    inspector_url=None,
                    rules=[],
                    download_urls=[],
                    queued_at=datetime.now() - timedelta(seconds=60),
                    queued_by="remmy",
                    pending_at=datetime.now() - timedelta(seconds=30),
                    pending_by="remmy",
                    finished_at=datetime.now() - timedelta(seconds=10),
                    finished_by="remmy",
                    reported_at=None,
                    reported_by=None,
                    fail_reason=None,
                    commit_hash="test commit hash",
                ),
            ],
            "c",
            "1.0.1",
            PackageAlreadyReported,
        ),
        (
            [
                Scan(
                    name="c",
                    version="1.0.0",
                    status=Status.FINISHED,
                    score=10,
                    inspector_url="test inspector url",
                    rules=[Rule(name="rule 1"), Rule(name="rule 2")],
                    download_urls=[DownloadURL(url="test download url")],
                    queued_at=datetime.now() - timedelta(seconds=60),
                    queued_by="remmy",
                    pending_at=datetime.now() - timedelta(seconds=30),
                    pending_by="remmy",
                    finished_at=datetime.now() - timedelta(seconds=10),
                    finished_by="remmy",
                    reported_at=datetime.now(),
                    reported_by="remmy",
                    fail_reason=None,
                    commit_hash="test commit hash",
                ),
                Scan(
                    name="c",
                    version="2.0.0",
                    status=Status.FINISHED,
                    score=10,
                    inspector_url="test inspector url",
                    rules=[Rule(name="rule 3"), Rule(name="rule 4")],
                    download_urls=[DownloadURL(url="test download url")],
                    queued_at=datetime.now() - timedelta(seconds=60),
                    queued_by="remmy",
                    pending_at=datetime.now() - timedelta(seconds=30),
                    pending_by="remmy",
                    finished_at=datetime.now(),
                    finished_by="remmy",
                    reported_at=None,
                    reported_by=None,
                    fail_reason=None,
                    commit_hash="test commit hash",
                ),
            ],
            "c",
            "2.0.0",
            PackageAlreadyReported,
        ),
    ],
)
def test_report_lookup_package_validation(
    scans: list[Scan], name: str, version: str, expected_exception: type[Exception]
):
    with pytest.raises(expected_exception):
        validate_package(name, version, scans)
