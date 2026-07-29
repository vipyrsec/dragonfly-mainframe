import datetime as dt
import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session, contains_eager
from sqlalchemy.sql.expression import text

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import get_rules, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.metrics import packages_dead_lettered, packages_fail
from mainframe.models.orm import DownloadURL, Scan, Status
from mainframe.models.schemas import JobResult
from mainframe.rules import Rules

router = APIRouter(tags=["job"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


def require_assignment_id(scan: Scan) -> uuid.UUID:
    """Return a claimed scan's assignment ID or fail on a broken database invariant."""
    if scan.assignment_id is None:
        msg = "Claimed scan is missing its assignment ID"
        raise RuntimeError(msg)
    return scan.assignment_id


def dead_letter_expired_scans(
    session: Session,
    *,
    retry_before: dt.datetime,
    dead_lettered_at: dt.datetime,
    max_job_attempts: int,
) -> list[Scan]:
    """Fail expired scans that have exhausted their worker assignment budget."""
    reason = f"Worker lease expired after {max_job_attempts} scan attempts"
    return list(
        session.scalars(
            update(Scan)
            .where(
                Scan.status == Status.PENDING,
                Scan.pending_at < retry_before,
                Scan.attempt_count >= max_job_attempts,
            )
            .values(
                status=Status.FAILED,
                fail_reason=reason,
                dead_lettered_at=dead_lettered_at,
            )
            .returning(Scan)
        )
    )


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
        scans.scan_id
    FROM scans
    WHERE
        scans.attempt_count < :max_job_attempts
        AND (
            scans.status = 'QUEUED'
            OR (
                scans.status = 'PENDING'
                AND scans.pending_at < :retry_before
            )
        )
    ORDER BY scans.pending_at NULLS FIRST, scans.queued_at
    LIMIT :batch
    FOR UPDATE OF scans SKIP LOCKED
), updated AS (
    UPDATE
        scans
    SET
        status = 'PENDING',
        pending_at = :pending_at,
        pending_by = :pending_by,
        attempt_count = scans.attempt_count + 1,
        assignment_id = gen_random_uuid()
    FROM packages
    WHERE scans.scan_id = packages.scan_id
    RETURNING scans.*
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
    updated.pending_at,
    updated.pending_by,
    updated.attempt_count,
    updated.assignment_id,
    updated.dead_lettered_at
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
        Scan.pending_by,
        Scan.attempt_count,
        Scan.assignment_id,
        Scan.dead_lettered_at,
    )

    query = (
        select(Scan)
        .from_statement(stmt)
        .options(contains_eager(Scan.download_urls))
        .execution_options(populate_existing=True)
    )
    pending_at = dt.datetime.now(dt.UTC)
    retry_before = pending_at - dt.timedelta(seconds=mainframe_settings.job_timeout)
    with session.begin():
        dead_lettered = dead_letter_expired_scans(
            session,
            retry_before=retry_before,
            dead_lettered_at=pending_at,
            max_job_attempts=mainframe_settings.max_job_attempts,
        )
        scans = (
            session.scalars(
                query,
                params={
                    "batch": batch,
                    "max_job_attempts": mainframe_settings.max_job_attempts,
                    "pending_at": pending_at,
                    "pending_by": auth.subject,
                    "retry_before": retry_before,
                },
            )
            .unique()
            .all()
        )

    if dead_lettered:
        packages_dead_lettered.inc(len(dead_lettered))
        packages_fail.inc(len(dead_lettered))
    for scan in dead_lettered:
        logger.error(
            "Scan attempt limit exhausted; package moved to dead letter",
            package={
                "attempt_count": scan.attempt_count,
                "name": scan.name,
                "pending_at": scan.pending_at,
                "pending_by": scan.pending_by,
                "version": scan.version,
            },
            reason=scan.fail_reason,
            tag="scan_dead_lettered",
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
                "attempt_count": scan.attempt_count,
                "version": scan.version,
            },
            tag="job_given",
        )

        job_result = JobResult(
            name=scan.name,
            version=scan.version,
            distributions=[dist.url for dist in scan.download_urls],
            hash=state.rules_commit,
            attempt=scan.attempt_count,
            assignment_id=require_assignment_id(scan),
        )

        response_body.append(job_result)

    return response_body
