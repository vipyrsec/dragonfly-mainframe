import datetime as dt
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from letsbuilda.pypi import PackageMetadata, PyPIServices
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import DownloadURL, Rule, Scan, Status
from mainframe.models.schemas import (
    BatchPackageQueueErr,
    Error,
    PackageScanResult,
    PackageSpecifier,
    QueuePackageResponse,
)

router = APIRouter(tags=["package"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@router.put(
    "/package",
    responses={
        400: {"model": Error},
        409: {"model": Error},
    },
)
async def submit_results(
    result: PackageScanResult,
    session: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
):
    name = result.name
    version = result.version
    scan = await session.scalar(
        select(Scan).where(Scan.name == name).where(Scan.version == version).options(selectinload(Scan.rules))
    )

    log = logger.bind(package={"name": name, "version": version})

    if scan is None:
        error = HTTPException(404, f"Package `{name}@{version}` not found in database.")
        await log.aerror(
            f"Package {name}@{version} not found in database", error_message=error.detail, tag="package_not_found_db"
        )
        raise error

    if scan.status == Status.FINISHED:
        error = HTTPException(409, f"Package `{name}@{version}` is already in a FINISHED state.")
        await log.aerror(
            f"Package {name}@{version} already in a FINISHED state", error_message=error.detail, tag="already_finished"
        )
        raise error

    scan.status = Status.FINISHED
    scan.finished_at = dt.datetime.now(dt.timezone.utc)
    scan.inspector_url = result.inspector_url
    scan.score = result.score
    scan.finished_by = auth.subject
    scan.commit_hash = result.commit

    # These are the rules that already have an entry in the database
    rules = await session.scalars(select(Rule).where(Rule.name.in_(result.rules_matched)))
    rule_names = {rule.name for rule in rules}
    scan.rules.extend(rules)

    # These are the rules that had to be created
    scan.rules.extend(Rule(name=rule_name) for rule_name in result.rules_matched if rule_name not in rule_names)

    await log.ainfo(
        "Scan results submitted",
        package={
            "name": name,
            "version": version,
            "status": scan.status,
            "finished_at": scan.finished_at,
            "inspector_url": result.inspector_url,
            "score": result.score,
            "finished_by": auth.subject,
        },
        tag="scan_submitted",
    )

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

    log = logger.bind(
        parameters={
            "name": name,
            "version": version,
            "since": since,
        }
    )

    if (not nn_name and not nn_since) or (nn_version and nn_since):
        await log.aerror(
            "Invalid parameter combination",
            error_message="Invalid parameter combination.",
            tag="invalid_parameter_combination",
        )
        raise HTTPException(status_code=400)

    query = select(Scan).options(selectinload(Scan.rules))
    if nn_name:
        query = query.where(Scan.name == name)
    if nn_version:
        query = query.where(Scan.version == version)
    if nn_since:
        query = query.where(Scan.finished_at >= dt.datetime.fromtimestamp(since, tz=dt.timezone.utc))

    data = await session.scalars(query)

    await log.ainfo("Package information queried")
    return data.all()


@router.post(
    "/batch/package",
    responses={
        409: {"model": Error},
        404: {"model": Error},
    },
)
async def batch_queue_package(
    packages: set[PackageSpecifier],
    session: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    request: Request,
) -> list[BatchPackageQueueErr]:
    ok_packages: dict[tuple[str, str], PackageMetadata] = {}
    err_packages: dict[tuple[str, str | None], str] = {}

    pypi_client: PyPIServices = request.app.state.pypi_client

    # This step filters out packages that are not even on PyPI
    for package in packages:
        name = package.name
        version = package.version

        try:
            package_metadata = await pypi_client.get_package_metadata(name, version)
            ok_packages[(package_metadata.info.name, package_metadata.info.version)] = package_metadata
        except KeyError:
            err_packages[(name, version)] = f"Package {name}@{version} was not found on PyPI"

    query = select(Scan).where(tuple_(Scan.name, Scan.version).in_(ok_packages))
    rows = await session.scalars(query)

    # This step filters out packages that are already in the database
    for row in rows:
        name = row.name
        version = row.version
        t = (name, version)

        ok_packages.pop(t)
        err_packages[t] = f"Package {name}@{version} is already queued for scanning"

    new_packages = [
        Scan(
            name=metadata.info.name,
            version=metadata.info.version,
            status=Status.QUEUED,
            queued_by=auth.subject,
            download_urls=[DownloadURL(url=url.url) for url in metadata.urls],
        )
        for metadata in ok_packages.values()
    ]

    session.add_all(new_packages)
    await session.commit()

    return [
        BatchPackageQueueErr(name=name, version=version, detail=detail)
        for ((name, version), detail) in err_packages.items()
    ]


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
    auth: Annotated[AuthenticationData, Depends(validate_token)],
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

    log = logger.bind(package={"name": name, "version": version})

    pypi_client: PyPIServices = request.app.state.pypi_client
    try:
        package_metadata = await pypi_client.get_package_metadata(name, version)
    except KeyError:
        error = HTTPException(404, detail=f"Package {name}@{version} was not found on PyPI")
        await log.aerror(
            f"Package {name}@{version} was not found on PyPI", error_message=error.detail, tag="package_not_found_pypi"
        )
        raise error

    version = package_metadata.info.version  # Use latest version if not provided
    log = logger.bind(package={"name": name, "version": version})

    query = select(Scan).where(Scan.name == name).where(Scan.version == version)
    row = await session.scalar(query)

    if row is not None:
        await log.info(f"Package {name}@{version} already queued for scanning.", tag="already_queued")
        raise HTTPException(409, f"Package {name}@{version} is already queued for scanning")

    new_package = Scan(
        name=name,
        version=version,
        status=Status.QUEUED,
        queued_by=auth.subject,
        download_urls=[DownloadURL(url=url.url) for url in package_metadata.urls],
    )

    session.add(new_package)
    await session.commit()

    await log.ainfo(
        "Added new package",
        package={
            "name": name,
            "version": version,
            "status": new_package.status,
            "queued_by": auth.subject,
            "download_urls": new_package.download_urls,
        },
        tag="package_added",
    )

    return QueuePackageResponse(id=str(new_package.scan_id))
