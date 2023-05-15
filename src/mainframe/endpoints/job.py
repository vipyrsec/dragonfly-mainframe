from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
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

    now = datetime.now()
    stmt = update(Package).where(Package.package_id == package.package_id).values(status=Status.PENDING, pending_at=now)
    await session.execute(stmt)
    await session.commit()

    return JobResult(package_id=package.package_id)
