from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from letsbuilda.pypi import PyPIServices
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mainframe.database import get_db
from mainframe.dependencies import get_pypi_client
from mainframe.models.orm import Package, Status
from mainframe.models.schemas import JobResult, NoJob

router = APIRouter()


@router.post("/job")
async def get_job(
    session: Annotated[AsyncSession, Depends(get_db)], pypi_client: Annotated[PyPIServices, Depends(get_pypi_client)]
) -> JobResult | NoJob:
    """Request a job to work on."""

    query = select(Package).where(Package.status == Status.QUEUED).order_by(Package.queued_at)
    scalars = await session.scalars(query)
    package = scalars.first()

    if not package:
        return NoJob(detail="No available packages to scan. Try again later.")

    package.status = Status.PENDING
    package.pending_at = datetime.utcnow()
    await session.commit()

    package_metadata = await pypi_client.get_package_metadata(package.name, package.version)
    distribution_urls = [distribution.url for distribution in package_metadata.urls]

    # FIXME: Add other package data needed by the client.
    return JobResult(name=package.name, version=package.version, distributions=distribution_urls)
