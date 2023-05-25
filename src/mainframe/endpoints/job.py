from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from letsbuilda.pypi import PyPIServices
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mainframe.database import get_db
from mainframe.models.orm import Package, Status
from mainframe.models.schemas import JobResult, NoJob

router = APIRouter()


def check_dead_client(pending_packages, request) -> Package | None:
    """check for dead client and retrieve job if client is dead"""
    for package in pending_packages:
        client_last_ping = request.app.state.clients.get(package.client_id)
        if datetime.utcnow() - client_last_ping > timedelta(minutes=15):
            return package
    return None


@router.post("/job")
async def get_job(session: Annotated[AsyncSession, Depends(get_db)], request: Request) -> JobResult | NoJob:
    """Request a job to work on."""

    # check pending packages for dead clients
    query = select(Package).where(Package.status == Status.PENDING).order_by(Package.queued_at)
    scalars = await session.scalars(query)
    package = check_dead_client(scalars, request)

    # check queued packages
    if not package:
        query = select(Package).where(Package.status == Status.QUEUED).order_by(Package.queued_at)
        scalars = await session.scalars(query)
        package = scalars.first()

    if not package:
        return NoJob(detail="No available packages to scan. Try again later.")

    package.status = Status.PENDING
    package.pending_at = datetime.utcnow()
    package.client_id = request.headers.get('Authorization')
    await session.commit()

    request.app.state.clients[package.client_id] = package.pending_at
    pypi_client: PyPIServices = request.app.state.pypi_client
    package_metadata = await pypi_client.get_package_metadata(package.name, package.version)
    distribution_urls = [distribution.url for distribution in package_metadata.urls]
    return JobResult(name=package.name, version=package.version, distributions=distribution_urls)
