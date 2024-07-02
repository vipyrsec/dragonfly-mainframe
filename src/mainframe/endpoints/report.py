import datetime as dt
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from letsbuilda.pypi import PackageNotFoundError, PyPIServices
from sqlalchemy.orm import Session

from mainframe.database import get_db
from mainframe.endpoints.package import lookup_package_info
from mainframe.dependencies import get_pypi_client, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.schemas import (
    EmailReport,
    Error,
    Observation,
    ObservationKind,
    Package,
    ReportPackageBody,
)

from mainframe.metrics import packages_reported
from mainframe.pypi_client import PyPIClientDependency

logger: structlog.stdlib.BoundLogger = structlog.get_logger()
router = APIRouter(tags=["report"])


def _validate_inspector_url(name: str, version: str, body_url: Optional[str], scan_url: Optional[str]) -> str:
    """
    Coalesce inspector_urls from ReportPackageBody and Scan.

    Returns:
        The inspector_url for the package.

    Raises:
        HTTPException: 400 Bad Request if the inspector_url was not passed in
            `body` and not found in the database.
    """
    log = logger.bind(package={"name": name, "version": version})

    inspector_url = body_url or scan_url
    if inspector_url is None:
        error = HTTPException(
            400,
            detail="inspector_url not given and not found in database",
        )
        log.error("Missing inspector_url field", error_message=error.detail, tag="missing_inspector_url")
        raise error

    return inspector_url


def _validate_additional_information(body: ReportPackageBody, scan: Package):
    """
    Validates the additional_information field.

    Returns:
        None if `body.additional_information` is valid.

    Raises:
        HTTPException: 400 Bad Request if `additional_information` was required
            and was not passed
    """
    log = logger.bind(package={"name": body.name, "version": body.version})

    if body.additional_information is None:
        if len(scan.rules) == 0 or body.use_email is False:
            if len(scan.rules) == 0:
                detail = (
                    f"additional_information is a required field as package "
                    f"`{body.name}@{body.version}` has no matched rules in the database"
                )
            else:
                detail = "additional_information is required when using Observation API"

            error = HTTPException(400, detail=detail)
            log.error(  
                "Missing additional_information field", error_message=detail, tag="missing_additional_information"
            )
            raise error


def _validate_pypi(name: str, version: str, pypi_client: PyPIServices):
    log = logger.bind(package={"name": name, "version": version})

    try:
        pypi_client.get_package_metadata(name, version)
    except PackageNotFoundError:
        error = HTTPException(404, detail="Package not found on PyPI")
        log.error("Package not found on PyPI", tag="package_not_found_pypi")
        raise error


@router.post(
    "/report{project_name}",
    responses={
        409: {"model": Error},
        400: {"model": Error},
    },
)
async def report_package(
    project_name: str,
    body: ReportPackageBody,
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    pypi_client: Annotated[PyPIServices, Depends(get_pypi_client)], 
    report_client: PyPIClientDependency
):
    """
    Report a package to PyPI.
    """

    name = body.name
    version = body.version

    log = logger.bind(package={"name": name, "version": version})
    scan: Package = lookup_package_info(name=name, version=version, session=session)[0]

    # This is bound to be changed to ´lookup_package_info.items` once https://github.com/vipyrsec/dragonfly-mainframe/pull/261 is accepted
    # As it currently stands, `lookup_package_info` returns a `list[Package]`, which will eventually change to `Page[Package]`,
    # Which has to be iterated (via `.items` property) to access thru the packages.
    # Or perhaps, this will be compl    etely disregarded and `_lookup_package` will be re-added. Let's see what happens.

    inspector_url = _validate_inspector_url(name, version, body.inspector_url, scan.inspector_url)
    _validate_additional_information(body, scan)
    _validate_pypi(name, version, pypi_client)

    rules_matched: list[str] = [rule for rule in scan.rules]

    if body.use_email is True:
        report = EmailReport(
            name=body.name,
            version=body.version,
            rules_matched=rules_matched,
            recipient=body.recipient,
            inspector_url=inspector_url,
            additional_information=body.additional_information,
        ) # reportUnusedVariable: false
        # await pypi_client.send_observation("email", report) 
        # I didn't fully get what's happening here.
        # I'll revisit this when I get an explanation.

    else:
        assert body.additional_information is not None
        report = Observation(
            kind=ObservationKind.Malware,
            summary=body.additional_information,
            inspector_url=inspector_url,
            extra=dict(yara_rules=rules_matched),
        )
    # await report_client.send_observation(project_name, report)
    # Type error.
    # I'll revisit this when I get a better grasp of what I'm doing, and how to integrate this more nicely.
    # Code's a freaking mess, this will be a draft first.

    log.info(
        "Sent report",
        report_data={
            "package_name": name,
            "package_version": version,
            "inspector_url": inspector_url,
            "additional_information": body.additional_information,
            "rules_matched": rules_matched,
            "use_email": body.use_email,
        },
        reported_by=auth.subject,
    )

    with session.begin():
        scan.reported_by = auth.subject
        scan.reported_at = dt.datetime.now(dt.timezone.utc)

    session.close()
    packages_reported.add(1)
