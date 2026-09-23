import datetime as dt
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from mainframe import ingestion
from mainframe.endpoints.package import batch_queue_package
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import IngestionRetry, Scan, Status
from mainframe.models.schemas import PackageSpecifier
from mainframe.pypi import Distribution, MetadataUnavailableError, PackageMetadata, PackageNotFoundError, PyPIClient


def test_partial_batch_survives_outage_and_recovers(
    engine: Engine,
    db_session: Session,
    auth: AuthenticationData,
    pypi_client: PyPIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy = PackageMetadata(name="healthy", version="1", distributions=[Distribution(url="https://example.org/a")])

    def metadata(name: str, _version: str) -> PackageMetadata:
        if name == "unavailable":
            raise MetadataUnavailableError(name)
        return healthy

    mock = MagicMock(side_effect=metadata)
    monkeypatch.setattr(pypi_client, "get_package_metadata", mock)
    packages = [PackageSpecifier(name=name, version="1") for name in ("healthy", "unavailable")]
    batch_queue_package(packages, db_session, auth, pypi_client)
    batch_queue_package(packages, db_session, auth, pypi_client)
    assert mock.call_count == 2
    with db_session.begin():
        assert db_session.scalar(select(Scan).where(Scan.name == "healthy")) is not None
        pending = db_session.get(IngestionRetry, ("unavailable", "1"))
        assert pending is not None
        assert pending.queued_by == auth.subject
        pending.retry_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)

    ingestion.retry_ingestion(engine, pypi_client)
    with Session(engine) as session:
        pending = session.get(IngestionRetry, ("unavailable", "1"))
        assert pending is not None
        assert pending.attempts == 1
        assert pending.retry_at > dt.datetime.now(dt.UTC)
    # A new process/session can recover the package after it leaves the feed.
    mock.side_effect = None
    mock.return_value = healthy.model_copy(update={"name": "unavailable"})
    with Session(engine) as session, session.begin():
        pending = session.get(IngestionRetry, ("unavailable", "1"))
        assert pending is not None
        pending.retry_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    ingestion.retry_ingestion(engine, pypi_client)
    ingestion.retry_ingestion(engine, pypi_client)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IngestionRetry)) == 0
        scan = session.scalar(select(Scan).where(Scan.name == "unavailable"))
        assert scan is not None
        assert scan.queued_by == auth.subject
        assert [url.url for url in scan.download_urls] == ["https://example.org/a"]


@pytest.mark.parametrize("existing", [True, False])
def test_retry_removes_completed_or_deleted_packages(
    engine: Engine,
    auth: AuthenticationData,
    pypi_client: PyPIClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    existing: bool,
) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            IngestionRetry(name="retry-test", version="1", queued_by=auth.subject, retry_at=dt.datetime.now(dt.UTC))
        )
        if existing:
            session.add(Scan(name="retry-test", version="1", status=Status.QUEUED, queued_by=auth.subject))
    mock = MagicMock(side_effect=PackageNotFoundError("retry-test", "1"))
    monkeypatch.setattr(pypi_client, "get_package_metadata", mock)
    ingestion.retry_ingestion(engine, pypi_client)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IngestionRetry)) == 0
    assert mock.call_count == (0 if existing else 1)


def test_retry_skips_locked_rows_and_bounds_work(
    engine: Engine,
    auth: AuthenticationData,
    pypi_client: PyPIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion, "RETRY_BATCH_SIZE", 1)
    now = dt.datetime.now(dt.UTC)
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                IngestionRetry(name=name, version="1", queued_by=auth.subject, retry_at=now)
                for name in ("locked", "available", "remaining")
            ]
        )
    with Session(engine) as locked, locked.begin():
        locked.scalar(select(IngestionRetry).where(IngestionRetry.name == "locked").with_for_update())
        ingestion.retry_ingestion(engine, pypi_client)
        assert locked.get(IngestionRetry, ("locked", "1")) is not None
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(IngestionRetry)) == 2
