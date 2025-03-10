from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager
from sqlalchemy.sql.expression import text

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import get_rules, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import DownloadURL, Scan
from mainframe.models.schemas import JobResult
from mainframe.rules import Rules

router = APIRouter(tags=["job"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@router.post("/jobs")
def get_jobs(
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    state: Annotated[Rules, Depends(get_rules)],
    batch: int = 1,
) -> list[JobResult]:
    """Request one or more releases to work on.

    Clients can specify the number of jobs they want to be given using the `batch` query string parameter.
    If omitted, it defaults to `1`.

    Clients are assigned the oldest release in the queue, i.e., the release with the oldest `queued_at` time.

    We also consider releases with a `pending_at` older than `now() - JOB_TIMEOUT` to be queued at the current time.
    This way, timed out packages are always processed after newly queued packages.
    """
    # See positional column targeting
    # https://docs.sqlalchemy.org/en/20/core/sqlelement.html#sqlalchemy.sql.expression.TextClause.columns
    # Query overview:
    # 1. select valid jobs and lock them
    # 2. update their status to pending
    # 3. select the updated rows and join download urls
    #
    # We need 2 CTEs because we need to LIMIT before joining the download urls.
    # If we were to join in the update, we will only get one of the download
    # urls for each scan, since Postgres will try to optimize and only update
    # one row, which will only return one download url.
    stmt = text("""\
WITH packages AS (
    SELECT
        scans.scan_id,
        scans.name,
        scans.version,
        scans.status,
        scans.queued_at,
        scans.queued_by,
        scans.pending_at
    FROM scans
    WHERE
        scans.status = 'QUEUED'
        OR (
            scans.status = 'PENDING'
            AND scans.pending_at < CURRENT_TIMESTAMP - INTERVAL ':job_timeout'
        )
    ORDER BY scans.pending_at NULLS FIRST, scans.queued_at
    LIMIT :batch
    FOR UPDATE OF scans SKIP LOCKED
), updated AS (
    UPDATE
        scans
    SET
        status = 'PENDING',
        pending_at = CURRENT_TIMESTAMP,
        pending_by = :pending_by
    FROM packages
    WHERE scans.scan_id = packages.scan_id
    RETURNING packages.*
)
SELECT
    download_urls.id,
    download_urls.scan_id,
    download_urls.url,
    updated.scan_id,
    updated.name,
    updated.version,
    updated.status,
    updated.queued_at,
    updated.queued_by,
    updated.pending_at
FROM updated
LEFT JOIN download_urls ON download_urls.scan_id = updated.scan_id
""").columns(
        DownloadURL.id,
        DownloadURL.scan_id,
        DownloadURL.url,
        Scan.scan_id,
        Scan.name,
        Scan.version,
        Scan.status,
        Scan.queued_at,
        Scan.queued_by,
        Scan.pending_at,
    )

    query = select(Scan).from_statement(stmt).options(contains_eager(Scan.download_urls))
    with session as s, s.begin():
        scans = (
            session.scalars(
                query,
                params={"job_timeout": mainframe_settings.job_timeout, "batch": batch, "pending_by": auth.subject},
            )
            .unique()
            .all()
        )

    response_body: list[JobResult] = []
    for scan in scans:
        logger.info(
            "Job given and status set to pending in database",
            package={
                "name": scan.name,
                "status": scan.status,
                "pending_at": scan.pending_at,
                "pending_by": auth.subject,
                "version": scan.version,
            },
            tag="job_given",
        )

        job_result = JobResult(
            name=scan.name,
            version=scan.version,
            distributions=[dist.url for dist in scan.download_urls],
            hash=state.rules_commit,
        )

        response_body.append(job_result)

    return response_body
