import datetime as dt
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from letsbuilda.pypi import PyPIServices
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mainframe.database import get_db
from mainframe.models.orm import DownloadURL, Package, Rule, Status
from mainframe.models.schemas import (
    Error,
    PackageScanResult,
    PackageSpecifier,
    QueuePackageResponse,
)

router = APIRouter()


@router.put(
    "/package",
    responses={
        400: {"model": Error},
        409: {"model": Error},
    },
)
async def submit_results(
    result: PackageScanResult, request: Request, session: Annotated[AsyncSession, Depends(get_db)]
):
    name = result.name
    version = result.version

    row = await session.scalar(
        select(Package)
        .where(Package.name == name)
        .where(Package.version == version)
        .options(selectinload(Package.rules))
    )

    if row is None:
        raise HTTPException(404, f"Package `{name}@{version}` not found in database.")

    if row.status == Status.FINISHED:
        raise HTTPException(409, f"Package `{name}@{version}` is already in a FINISHED state.")

    row.status = Status.FINISHED
    row.finished_at = dt.datetime.utcnow()
    row.inspector_url = result.inspector_url
    row.score = result.score

    for rule_name in result.rules_matched:
        rule = await session.scalar(select(Rule).where(Rule.name == rule_name))
        if rule is None:
            raise HTTPException(400, f"Rule '{rule_name}' is not a valid rule for package `{name}@{version}`")

        row.rules.append(rule)

    await session.commit()


@router.get("/package", responses={400: {"model": Error, "description": "Invalid parameter combination."}})
async def lookup_package_info(
    session: Annotated[AsyncSession, Depends(get_db)],
    since: Optional[int] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
):
    """
    Lookup information on scanned packages based on name, version, or time scanned.

    Args:
        since: A int representing a Unix timestamp representing when to begin the search from.
        name: The name of the package.
        version: The version of the package.
        session: DB session.

    Only certain combinations of parameters are allowed. A query is valid if any of the following combinations are used:
        - `name` and `version`: Return the package with name `name` and version `version`, if it exists.
        - `name` and `since`: Find all packages with name `name` since `since`.
        - `since`: Find all packages since `since`.
        - `name`: Find all packages with name `name`.
    All other combinations are disallowed.

    In more formal terms, a query is valid
        iff `((name and not since) or (not version and since))`
    where a given variable name means that query parameter was passed. Equivalently, a request is invalid
        iff `(not (name or since) or (version and since))`
    """

    nn_name = name is not None
    nn_version = version is not None
    nn_since = since is not None

    if (not nn_name and not nn_since) or (nn_version and nn_since):
        raise HTTPException(status_code=400)

    query = select(Package).options(selectinload(Package.rules))
    if nn_name:
        query = query.where(Package.name == name)
    if nn_version:
        query = query.where(Package.version == version)
    if nn_since:
        query = query.where(Package.finished_at >= dt.datetime.utcfromtimestamp(since))

    data = await session.scalars(query)
    return data.all()


@router.post(
    "/package",
    responses={
        409: {"model": Error},
        404: {"model": Error},
    },
)
async def queue_package(
    package: PackageSpecifier,
    session: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> QueuePackageResponse:
    """
    Queue a package to be scanned when the next runner is available
    Args:
        Body: Request body paramters
        session: Database session
        pypi_client: client instance used to interact with PyPI JSON API
    Returns:
        404: The given package and version combination was not found on PyPI
        409: The given package and version combination has already been queued
    """

    name = package.name
    version = package.version

    pypi_client: PyPIServices = request.app.state.pypi_client
    try:
        package_metadata = await pypi_client.get_package_metadata(name, version)
    except KeyError:
        raise HTTPException(404, detail=f"Package {name}@{version} was not found on PyPI")

    version = package_metadata.info.version  # Use latest version if not provided

    query = select(Package).where(Package.name == name).where(Package.version == version)
    row = await session.scalar(query)

    if row is not None:
        raise HTTPException(409, f"Package {name}@{version} is already queued for scanning")

    new_package = Package(
        name=name,
        version=version,
        status=Status.QUEUED,
        download_urls=[DownloadURL(url=url.url) for url in package_metadata.urls],
    )

    session.add(new_package)
    await session.commit()

    return QueuePackageResponse(id=str(new_package.package_id))
