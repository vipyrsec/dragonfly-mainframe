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
    EmailReport,
    Error,
    ObservationKind,
    ObservationReport,
    ReportPackageBody,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


router = APIRouter(tags=["report"])


def get_reported_version(scans: Sequence[Scan]) -> Optional[Scan]:
    """
    Get the version of this scan that was reported.

    Returns:
        `Scan`: The scan record that was reported
        `None`: No versions of this package were reported
    """

    for scan in scans:
        if scan.reported_at is not None:
            return scan

    return None


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

    if not scans:
        raise PackageNotFound(name=name, version=version)

    if scan := get_reported_version(scans):
        raise PackageAlreadyReported(name=scan.name, reported_version=scan.version)

    scan = next((s for s in scans if (s.name, s.version) == (name, version)), None)
    if scan is None:
        raise PackageNotFound(name=name, version=version)

    return scan


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


def _validate_additional_information(body: ReportPackageBody, scan: Scan):
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

    The optional `use_email` field can be used to send reports by email. This
    defaults to `False`.

    There are some restrictions on what packages can be reported. They must:
    - exist in the database
    - exist on PyPI
    - not already be reported

    While the `inspector_url` and `additional_information` fields are optional
    in the schema, the API requires you to provide them in certain cases. Some
    of those are outlined below.

    `inspector_url` and `additional_information` both must be provided if the
    package being reported is in a `QUEUED` or `PENDING` state. That is, the
    package has not yet been scanned and therefore has no records for
    `inspector_url` or any matched rules

    If the package has successfully been scanned (that is, it is in
    a `FINISHED` state), and it has been determined to be malicious, then
    neither `inspector_url` nor `additional_information` is required. If the
    `inspector_url` is omitted, then it will default to a URL that points to
    the file with the highest total score.

    If the package has successfully been scanned (that is, it is in
    a `FINISHED` state), and it has been determined NOT to be malicious (that
    is, it has no matched rules), then you must provide `inspector_url` AND
    `additional_information`.
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
    _validate_additional_information(body, scan)

    # If execution reaches here, we must have found a matching scan in our
    # database. Check if the package we want to report exists on PyPI.
    _validate_pypi(name, version, httpx_client)

    rules_matched: list[str] = [rule.name for rule in scan.rules]

    if body.use_email is True:
        report = EmailReport(
            name=body.name,
            version=body.version,
            rules_matched=rules_matched,
            recipient=body.recipient,
            inspector_url=inspector_url,
            additional_information=body.additional_information,
        )

        httpx_client.post(f"{mainframe_settings.reporter_url}/report/email", json=jsonable_encoder(report))
    else:
        # We previously checked this condition, but the typechecker isn't smart
        # enough to figure that out
        assert body.additional_information is not None

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
            "use_email": body.use_email,
        },
        reported_by=auth.subject,
    )
