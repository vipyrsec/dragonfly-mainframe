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
from mainframe.models.orm import Scan, Status
from mainframe.models.schemas import JobResult

router = APIRouter(tags=["job"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@router.post("/jobs")
async def get_jobs(
    session: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    request: Request,
    batch: int = 1,
) -> list[JobResult]:
    """
    Request one or more releases to work on.

    Clients can specify the number of jobs they want to be given
    using the `batch` query string parameter. If omitted, it defaults
    to `1`.

    Clients are assigned the oldest release in the queue, i.e., the release
    with the oldest `queued_at` time.

    We also consider releases with a `pending_at` older than
    `now() - JOB_TIMEOUT` to be queued at the current time. This way, timed out
    packages are always processed after newly queued packages.
    """

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
        .limit(batch)
        .options(selectinload(Scan.download_urls))
        .with_for_update()
    )

    scans = scalars.all()

    response_body: list[JobResult] = []
    for scan in scans:
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

        job_result = JobResult(
            name=scan.name,
            version=scan.version,
            distributions=[dist.url for dist in scan.download_urls],
            hash=request.app.state.rules.rules_commit,
        )

        response_body.append(job_result)

    await session.commit()

    return response_body
