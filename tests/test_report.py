from datetime import datetime, timedelta
from copy import deepcopy
from typing import Optional
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mainframe.endpoints.report import (
    _lookup_package,  # pyright: ignore [reportPrivateUsage]
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


def test_report(
    sm: sessionmaker[Session],
    db_session: Session,
    auth: AuthenticationData,
):
    body = ReportPackageBody(
        name="c",
        version="1.0.0",
        inspector_url=None,
        additional_information="this package is bad",
    )

    report = ObservationReport(
        kind=ObservationKind.Malware,
        summary="this package is bad",
        inspector_url="test inspector url",
        extra=dict(yara_rules=["rule 1", "rule 2"]),
    )
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

    with db_session.begin():
        db_session.add(scan)

    mock_httpx_client = MagicMock()

    report_package(body, sm(), auth, mock_httpx_client)

    mock_httpx_client.post.assert_called_once_with("/report/c", json=jsonable_encoder(report))

    with sm() as sess, sess.begin():
        s = sess.scalar(select(Scan).where(Scan.name == "c").where(Scan.version == "1.0.0"))

    assert s is not None
    assert s.reported_by == auth.subject
    assert s.reported_at is not None


def test_report_package_not_on_pypi():
    mock_httpx_client = MagicMock(spec=httpx.Client)
    mock_httpx_client.configure_mock(**{"get.return_value.status_code": 404})

    with pytest.raises(HTTPException) as e:
        _validate_pypi("c", "1.0.0", mock_httpx_client)
    assert e.value.status_code == 404


def test_report_unscanned_package(db_session: Session):
    with pytest.raises(HTTPException) as e:
        _lookup_package("c", "1.0.0", db_session)
    assert e.value.status_code == 404


def test_report_invalid_version(db_session: Session):
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
        finished_at=datetime.now() - timedelta(seconds=10),
        finished_by="remmy",
        reported_at=None,
        reported_by="remmy",
        fail_reason=None,
        commit_hash="test commit hash",
    )
    with db_session.begin():
        db_session.add(scan)

    with pytest.raises(HTTPException) as e:
        _lookup_package("c", "2.0.0", db_session)
    assert e.value.status_code == 404


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
    ("scans", "name", "version", "expected_status_code"),
    [
        ([], "a", "1.0.0", 404),
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
            409,
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
            409,
        ),
    ],
)
def test_report_lookup_package_validation(
    db_session: Session, scans: list[Scan], name: str, version: str, expected_status_code: int
):
    with db_session.begin():
        db_session.add_all(deepcopy(scans))

    with pytest.raises(HTTPException) as e:
        _lookup_package(name, version, db_session)
    assert e.value.status_code == expected_status_code


def test_report_lookup_package(db_session: Session):
    scan = Scan(
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
    )

    with db_session.begin():
        db_session.add(scan)

    res = _lookup_package("c", "1.0.0", db_session)

    assert res == scan
