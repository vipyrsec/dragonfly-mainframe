from collections.abc import Sequence
from typing import Annotated, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from mainframe.constants import mainframe_settings
from mainframe.custom_exceptions import PackageNotFound, PackageAlreadyReported
from mainframe.database import StorageProtocol, get_storage
from mainframe.dependencies import get_httpx_client, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan
from mainframe.models.schemas import (
    Error,
    ObservationKind,
    ObservationReport,
    ReportPackageBody,
)

from mainframe.metrics import packages_reported

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


router = APIRouter(tags=["report"])


def validate_package(name: str, version: str, scans: Sequence[Scan]) -> Scan:
    """
    Checks if the package is valid according to our database.
    A package is considered valid if there exists a scan with the given name
    and version, and that no other versions have been reported.

    Arguments:
        name: The name of the package to validate
        version: The version of the package to validate
        scans: The sequence of Scan records in the database where name=name

    Returns:
        `Scan`: The validated `Scan` object

    Raises:
        PackageNotFound: The given name and version combination was not found
        PackageAlreadyReported: The package was already reported
    """

    for scan in scans:
        if scan.reported_at is not None:
            raise PackageAlreadyReported(name=scan.name, reported_version=scan.version)

    for scan in scans:
        if (scan.name, scan.version) == (name, version):
            return scan

    raise PackageNotFound(name=name, version=version)


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


def _validate_pypi(name: str, version: str, http_client: httpx.Client):
    log = logger.bind(package={"name": name, "version": version})

    response = http_client.get(f"https://pypi.org/project/{name}")
    if response.status_code == 404:
        error = HTTPException(404, detail="Package not found on PyPI")
        log.error("Package not found on PyPI", tag="package_not_found_pypi")
        raise error


@router.post(
    "/report",
    responses={
        409: {"model": Error},
        400: {"model": Error},
    },
)
def report_package(
    body: ReportPackageBody,
    database: Annotated[StorageProtocol, Depends(get_storage)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    httpx_client: Annotated[httpx.Client, Depends(get_httpx_client)],
):
    """
    Report a package to PyPI.

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
    try:
        scans = database.lookup_packages(name)
        scan = validate_package(name, version, scans)
    except PackageNotFound as e:
        detail = f"No records for package `{e.name} v{e.version}` were found in the database"
        error = HTTPException(404, detail=detail)
        log.error(detail, error_message=detail, tag="package_not_found_db")

        raise error
    except PackageAlreadyReported as e:
        detail = (
            f"Only one version of a package may be reported at a time "
            f"(`{e.name}@{e.reported_version}` was already reported)"
        )
        error = HTTPException(409, detail=detail)
        log.error(detail, error_message=error.detail, tag="multiple_versions_prohibited")

        raise error
    inspector_url = _validate_inspector_url(name, version, body.inspector_url, scan.inspector_url)

    # If execution reaches here, we must have found a matching scan in our
    # database. Check if the package we want to report exists on PyPI.
    _validate_pypi(name, version, httpx_client)

    rules_matched: list[str] = [rule.name for rule in scan.rules]

    report = ObservationReport(
        kind=ObservationKind.Malware,
        summary=body.additional_information,
        inspector_url=inspector_url,
        extra=dict(yara_rules=rules_matched),
    )

    httpx_client.post(f"{mainframe_settings.reporter_url}/report/{name}", json=jsonable_encoder(report))

    database.mark_reported(scan=scan, subject=auth.subject)

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
