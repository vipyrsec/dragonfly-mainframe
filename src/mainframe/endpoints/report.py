import datetime as dt
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import get_httpx_client, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.metrics import packages_reported
from mainframe.models.orm import Scan
from mainframe.models.schemas import (
    Error,
    ObservationKind,
    ObservationReport,
    ReportPackageBody,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


router = APIRouter(tags=["report"])


def _lookup_package(name: str, version: str, session: Session) -> Scan:
    """Checks if the package is valid according to our database.

    Returns:
        The scan, if the package exists in the database.

    Raises:
        HTTPException:
            404 Not Found, if the name was not found in the database,
                or the specified name and version was not found in the database.
            409 Conflict, if another version of the same package has already been reported.
    """
    log = logger.bind(package={"name": name, "version": version})

    query = select(Scan).where(Scan.name == name).options(joinedload(Scan.rules))
    with session.begin():
        scans = session.scalars(query).unique().all()

    if not scans:
        error = HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"No records for package `{name}` were found in the database",
        )
        log.error(
            f"No records for package {name} found in database",
            error_message=error.detail,
            tag="package_not_found_db",
        )
        raise error

    for scan in scans:
        if scan.reported_at is not None:
            error = HTTPException(
                status.HTTP_409_CONFLICT,
                detail=(
                    "Only one version of a package may be reported at a time "
                    f"(`{scan.name}@{scan.version}` was already reported)"
                ),
            )
            log.error(
                "Only one version of a package allowed to be reported at a time",
                error_message=error.detail,
                tag="multiple_versions_prohibited",
            )
            raise error

    with session.begin():
        scan = session.scalar(query.where(Scan.version == version))
    if scan is None:
        error = HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Package `{name}` has records in the database, but none with version `{version}`",
        )
        log.error(
            f"No version {version} for package {name} in database",
            error_message=error.detail,
            tag="invalid_version",
        )
        raise error

    return scan


def _validate_inspector_url(name: str, version: str, body_url: str | None, scan_url: str | None) -> str:
    """Coalesce inspector_urls from ReportPackageBody and Scan.

    Returns:
        The inspector_url for the package.

    Raises:
        HTTPException: 400 Bad Request, if the inspector_url was not passed in `body` and not found in the database.
    """
    log = logger.bind(package={"name": name, "version": version})

    inspector_url = body_url or scan_url
    if inspector_url is None:
        error = HTTPException(status.HTTP_404_NOT_FOUND, detail="inspector_url not given and not found in database")
        log.error("Missing inspector_url field", error_message=error.detail, tag="missing_inspector_url")
        raise error

    return inspector_url


def _validate_pypi(name: str, version: str, http_client: httpx.Client) -> None:
    log = logger.bind(package={"name": name, "version": version})

    response = http_client.get(f"https://pypi.org/project/{name}")
    if response.status_code == httpx.codes.NOT_FOUND:
        error = HTTPException(status.HTTP_404_NOT_FOUND, detail="Package not found on PyPI")
        log.error("Package not found on PyPI", tag="package_not_found_pypi")
        raise error


@router.post(
    "/report",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": Error},
        status.HTTP_409_CONFLICT: {"model": Error},
    },
)
def report_package(
    body: ReportPackageBody,
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    httpx_client: Annotated[httpx.Client, Depends(get_httpx_client)],
) -> None:
    """Report a package to PyPI.

    There are some restrictions on what packages can be reported. They must:
    - exist in the database
    - exist on PyPI
    - not already be reported

    `inspector_url` argument is required if the package has no matched rules.
    If `inspector_url` argument is not provided for a package with matched rules,
    the Inspector URL of the file with the highest total score will be used.
    If `inspector_url` argument is provided for a package with matched rules,
    the given Inspector URL will override the default one.
    """
    name = body.name
    version = body.version

    log = logger.bind(package={"name": name, "version": version})

    # Check our database first to avoid unnecessarily using PyPI API.
    scan = _lookup_package(name, version, session)
    inspector_url = _validate_inspector_url(name, version, body.inspector_url, scan.inspector_url)

    # If execution reaches here, we must have found a matching scan in our
    # database. Check if the package we want to report exists on PyPI.
    _validate_pypi(name, version, httpx_client)

    rules_matched: list[str] = [rule.name for rule in scan.rules]

    report = ObservationReport(
        kind=ObservationKind.Malware,
        summary=body.additional_information,
        inspector_url=inspector_url,
        extra={"yara_rules": rules_matched},
    )

    httpx_client.post(f"{mainframe_settings.reporter_url}/report/{name}", json=jsonable_encoder(report))

    with session.begin():
        scan.reported_by = auth.subject
        scan.reported_at = dt.datetime.now(dt.UTC)

    session.close()

    log.info(
        "Sent report",
        report_data={
            "package_name": name,
            "package_version": version,
            "inspector_url": inspector_url,
            "additional_information": body.additional_information,
            "rules_matched": rules_matched,
        },
        reported_by=auth.subject,
    )

    packages_reported.inc()
