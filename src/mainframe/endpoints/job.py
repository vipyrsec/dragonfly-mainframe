from datetime import datetime, timedelta, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Package, Status
from mainframe.models.schemas import JobResult, NoJob

router = APIRouter(tags=["job"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


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

    scalars = await session.scalars(
        select(Package)
        .where(
            or_(
                Package.status == Status.QUEUED,
                and_(
                    Package.pending_at < datetime.now(timezone.utc) - timedelta(seconds=mainframe_settings.job_timeout),
                    Package.status == Status.PENDING,
                ),
            )
        )
        .order_by(Package.pending_at.nulls_first(), Package.queued_at)
        .options(selectinload(Package.download_urls))
        .with_for_update()
    )
    package = scalars.first()

    if not package:
        logger.info("No packages available to scan, job not given.", tag="no_packages")
        return NoJob(detail="No available packages to scan. Try again later.")

    package.status = Status.PENDING
    package.pending_at = datetime.now(timezone.utc)
    package.pending_by = auth.subject
    await session.commit()

    distribution_urls = [distribution.url for distribution in package.download_urls]

    await logger.ainfo(
        "Job given and status set to pending in database",
        package={
            "name": package.name,
            "status": package.status,
            "pending_at": package.pending_at,
            "pending_by": auth.subject,
            "version": package.version,
        },
        tag="job_given",
    )

    return JobResult(
        name=package.name,
        version=package.version,
        distributions=distribution_urls,
        hash=request.app.state.rules.rules_commit,
    )
