"""Bounded retries of durably accepted packages, independent of the RSS feed."""

import datetime as dt
import logging

from prometheus_client import Counter, Gauge
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from mainframe.metrics import packages_ingested
from mainframe.models.orm import DownloadURL, IngestionRetry, Scan, Status
from mainframe.pypi import MetadataUnavailableError, PackageNotFoundError, PyPIClient

retry_results = Counter("ingestion_retry_results_total", "Metadata retry outcomes", ["result"])
retry_backlog = Gauge("ingestion_retry_backlog", "Packages awaiting upstream metadata")
RETRY_BATCH_SIZE = 20


def retry_ingestion(engine: Engine, pypi_client: PyPIClient) -> None:
    """Lock one due package at a time; retain failures with bounded backoff."""
    now = dt.datetime.now(dt.UTC)
    for _ in range(RETRY_BATCH_SIZE):
        with Session(engine) as session, session.begin():
            pending = session.scalar(
                select(IngestionRetry)
                .where(IngestionRetry.retry_at <= now)
                .order_by(IngestionRetry.retry_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if pending is None:
                break
            result = retry_package(session, pending, pypi_client, now)
        retry_results.labels(result).inc()
        if result == "ingested":
            packages_ingested.inc()
    with Session(engine) as session:
        retry_backlog.set(session.scalar(select(func.count()).select_from(IngestionRetry)) or 0)


def retry_package(session: Session, pending: IngestionRetry, pypi_client: PyPIClient, now: dt.datetime) -> str:
    if session.scalar(select(Scan.scan_id).where(Scan.name == pending.name, Scan.version == pending.version)):
        session.delete(pending)
        return "already_ingested"
    try:
        metadata = pypi_client.get_package_metadata(pending.name, pending.version)
    except MetadataUnavailableError:
        pending.attempts += 1
        pending.retry_at = now + dt.timedelta(seconds=min(3600, 60 * 2 ** min(pending.attempts, 6)))
        logging.getLogger(__name__).warning("PyPI metadata still unavailable for %s@%s", pending.name, pending.version)
        return "unavailable"
    except PackageNotFoundError:
        session.delete(pending)
        return "not_found"
    session.add(
        Scan(
            name=metadata.name,
            version=metadata.version,
            status=Status.QUEUED,
            queued_by=pending.queued_by,
            download_urls=[DownloadURL(url=distribution.url) for distribution in metadata.distributions],
        )
    )
    session.delete(pending)
    return "ingested"
