from datetime import datetime, timedelta
from typing import cast
from unittest.mock import MagicMock

from letsbuilda.pypi import PyPIServices
from msgraph.core import GraphClient
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
        additional_information=None,
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
