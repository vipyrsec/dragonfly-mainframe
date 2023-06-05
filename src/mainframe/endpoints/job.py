from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mainframe.database import get_db
from mainframe.models.orm import Package, Status
from mainframe.models.schemas import JobResult, NoJob

router = APIRouter()


@router.post("/job")
async def get_job(session: Annotated[AsyncSession, Depends(get_db)], request: Request) -> JobResult | NoJob:
    """Request a job to work on."""

    scalars = await session.scalars(
        select(Package)
        .where(Package.status == Status.QUEUED)
        .order_by(Package.queued_at)
        .options(selectinload(Package.download_urls))
        .with_for_update()
    )
    package = scalars.first()

    if not package:
        return NoJob(detail="No available packages to scan. Try again later.")

    package.status = Status.PENDING
    package.pending_at = datetime.utcnow()
    await session.commit()

    distribution_urls = [distribution.url for distribution in package.download_urls]
    return JobResult(
        name=package.name,
        version=package.version,
        distributions=distribution_urls,
        hash=request.app.state.rules.rules_commit,
    )
