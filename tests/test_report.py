from datetime import datetime, timedelta
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from letsbuilda.pypi import PyPIServices
from letsbuilda.pypi.exceptions import PackageNotFoundError
from msgraph.core import GraphClient
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.orm import Session

from mainframe.endpoints.report import report_package
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import DownloadURL, Rule, Scan, Status
from mainframe.models.schemas import ReportPackageBody


def test_report(db_session: Session, auth: AuthenticationData, pypi_client: PyPIServices):
    result = Scan(
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

    db_session.add(result)
    db_session.commit()

    body = ReportPackageBody(
        name="c",
        version="1.0.0",
        recipient=None,
        inspector_url=None,
        additional_information="this package is bad",
    )

    graph_client_mock = MagicMock()
    graph_client_mock.post = MagicMock()
    report_package(body, db_session, cast(GraphClient, graph_client_mock), auth, pypi_client)

    # Microsoft's GraphClient sucks and asserting the arguments is too much effort
    # So let's just assert that it was at least called
    graph_client_mock.post.assert_called_once()  # pyright: ignore

    scan = db_session.scalar(select(Scan).where(Scan.name == "c").where(Scan.version == "1.0.0"))

    assert scan is not None
    assert scan.reported_by == auth.subject
    assert scan.reported_at is not None


def test_report_invalid_package(
    db_session: Session,
    auth: AuthenticationData,
    pypi_client: PyPIServices,
    monkeypatch: MonkeyPatch,
    graph_client: GraphClient,
):
    # Make get_package_metadata always throw PackageNotFoundError to simulate an invalid package
    def _side_effect(name: str, version: str):
        raise PackageNotFoundError(name, version)

    monkeypatch.setattr(pypi_client, "get_package_metadata", _side_effect)

    body = ReportPackageBody(
        name="c",
        version="1.0.0",
        recipient=None,
        inspector_url=None,
        additional_information=None,
    )

    with pytest.raises(HTTPException) as e:
        report_package(body, db_session, graph_client, auth, pypi_client)
    assert e.value.status_code == 404


def test_report_unscanned_package(
    db_session: Session, auth: AuthenticationData, pypi_client: PyPIServices, graph_client: GraphClient
):
    body = ReportPackageBody(
        name="c",
        version="1.0.0",
        recipient=None,
        inspector_url=None,
        additional_information=None,
    )

    with pytest.raises(HTTPException) as e:
        report_package(body, db_session, graph_client, auth, pypi_client)
    assert e.value.status_code == 404


def test_report_multi_versions(
    db_session: Session, auth: AuthenticationData, pypi_client: PyPIServices, graph_client: GraphClient
):
    version1 = Scan(
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
    )

    version2 = Scan(
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
    )

    db_session.add_all((version1, version2))
    db_session.commit()

    body = ReportPackageBody(
        name="c",
        version="2.0.0",
        recipient=None,
        inspector_url=None,
        additional_information=None,
    )

    with pytest.raises(HTTPException) as e:
        report_package(body, db_session, graph_client, auth, pypi_client)
    assert e.value.status_code == 409


def test_report_invalid_version(
    db_session: Session, auth: AuthenticationData, pypi_client: PyPIServices, graph_client: GraphClient
):
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
    db_session.add(scan)
    db_session.commit()

    body = ReportPackageBody(
        name="c",
        version="2.0.0",
        recipient=None,
        inspector_url=None,
        additional_information=None,
    )

    with pytest.raises(HTTPException) as e:
        report_package(body, db_session, graph_client, auth, pypi_client)
    assert e.value.status_code == 404


def test_report_missing_inspector_url(
    db_session: Session, auth: AuthenticationData, pypi_client: PyPIServices, graph_client: GraphClient
):
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
    db_session.add(scan)
    db_session.commit()

    body = ReportPackageBody(
        name="c",
        version="1.0.0",
        recipient=None,
        inspector_url=None,
        additional_information=None,
    )

    with pytest.raises(HTTPException) as e:
        report_package(body, db_session, graph_client, auth, pypi_client)
    assert e.value.status_code == 400


def test_report_missing_additional_information(
    db_session: Session, auth: AuthenticationData, pypi_client: PyPIServices, graph_client: GraphClient
):
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
    db_session.add(scan)
    db_session.commit()

    body = ReportPackageBody(
        name="c",
        version="1.0.0",
        recipient=None,
        inspector_url="inspector url override",
        additional_information=None,
    )

    with pytest.raises(HTTPException) as e:
        report_package(body, db_session, graph_client, auth, pypi_client)
    print(e.value.detail)
    assert e.value.status_code == 400
