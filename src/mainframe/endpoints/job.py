from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mainframe.database import get_db
from mainframe.models.orm import Package, Status
from mainframe.models.schemas import JobResult, NoJob

router = APIRouter()


@router.post("/job")
async def get_job(session: AsyncSession = Depends(get_db)) -> JobResult | NoJob:
    """Request a job to work on."""

    query = select(Package).where(Package.status == Status.QUEUED).order_by(Package.queued_at)
    scalars = await session.scalars(query)
    package = scalars.first()

    if not package:
        return NoJob(detail="No available packages to scan. Try again later.")

    package.status = Status.PENDING
    package.pending_at = datetime.utcnow()
    await session.commit()

    # FIXME: Add other package data needed by the client.
    return JobResult(package_id=package.package_id, name=package.name, version=package.version)
