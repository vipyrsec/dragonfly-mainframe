from datetime import datetime, timedelta, timezone
from typing import Annotated, Sequence

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan, Status
from mainframe.models.schemas import JobResult, NoJob

router = APIRouter(tags=["job"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


def _build_response(scans: Sequence[Scan], *, hash: str) -> list[JobResult]:
    """Build the HTTP response to send to clients based on the rows from the DB"""
    return [
        JobResult(
            name=scan.name,
            version=scan.version,
            distributions=[dist.url for dist in scan.download_urls],
            hash=hash,
        )
        for scan in scans
    ]


async def fetch_jobs(*, n_jobs: int, session: AsyncSession) -> Sequence[Scan]:
    """Fetch `n_jobs` amount of jobs from the database, using the given `session`"""
    scalars = await session.scalars(
        select(Scan)
        .where(
            or_(
                Scan.status == Status.QUEUED,
                and_(
                    Scan.pending_at < datetime.now(timezone.utc) - timedelta(seconds=mainframe_settings.job_timeout),
                    Scan.status == Status.PENDING,
                ),
            )
        )
        .order_by(Scan.pending_at.nulls_first(), Scan.queued_at)
        .limit(n_jobs)
        .options(selectinload(Scan.download_urls))
        .with_for_update()
    )

    return scalars.all()


@router.get("/batch/job")
async def get_batch_job(
    n_jobs: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    request: Request,
) -> list[JobResult]:
    """
    Request multiple releases to work on.

    This functions almost identically to `POST /job`,
    however this returns an array of results
    """

    scans = await fetch_jobs(n_jobs=n_jobs, session=session)
    for scan in scans:
        scan.status = Status.PENDING
        scan.pending_at = datetime.now(timezone.utc)
        scan.pending_by = auth.subject

    response = _build_response(scans, hash=request.app.state.rules.rules_commit)
    await session.commit()

    return response


@router.post("/job")
async def get_job(
    session: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    request: Request,
) -> JobResult | NoJob:
    """
    Request a release to work on.

    Clients are assigned the oldest release in the queue, i.e., the release
    with the oldest `queued_at` time.

    We also consider releases with a `pending_at` older than
    `now() - JOB_TIMEOUT` to be queued at the current time. This way, timed out
    packages are always processed after newly queued packages.
    """

    scans = await fetch_jobs(n_jobs=1, session=session)
    if not scans:
        logger.info("No scans available, job not given.", tag="no_packages")
        return NoJob(detail="No scans available. Try again later.")

    scan = scans[0]
    scan.status = Status.PENDING
    scan.pending_at = datetime.now(timezone.utc)
    scan.pending_by = auth.subject

    await logger.ainfo(
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

    response = _build_response(scans, hash=request.app.state.rules.rules_commit)
    await session.commit()

    return response[0]
