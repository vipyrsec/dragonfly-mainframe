import datetime as dt
from typing import Annotated, Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from letsbuilda.pypi import PackageNotFoundError, PyPIServices
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import get_pypi_client, validate_token
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


def _lookup_package(name: str, version: str, session: Session) -> Scan:
    """
    Checks if the package is valid according to our database.

    Returns:
        True if the package exists in the database.

    Raises:
        HTTPException: 404 Not Found if the name was not found in the database,
            or the specified name and version was not found in the database. 409
            Conflict if another version of the same package has already been
            reported.
    """

    log = logger.bind(package={"name": name, "version": version})

    query = select(Scan).where(Scan.name == name).options(joinedload(Scan.rules))
    with session.begin():
        scans = session.scalars(query).unique().all()

    if not scans:
        error = HTTPException(404, detail=f"No records for package `{name}` were found in the database")
        log.error(
            f"No records for package {name} found in database", error_message=error.detail, tag="package_not_found_db"
        )
        raise error

    for scan in scans:
        if scan.reported_at is not None:
            error = HTTPException(
                409,
                detail=(
                    f"Only one version of a package may be reported at a time. "
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
            404, detail=f"Package `{name}` has records in the database, but none with version `{version}`"
        )
        log.error(f"No version {version} for package {name} in database", tag="invalid_version")
        raise error

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


def _validate_pypi(name: str, version: str, pypi_client: PyPIServices):
    log = logger.bind(package={"name": name, "version": version})

    try:
        pypi_client.get_package_metadata(name, version)
    except PackageNotFoundError:
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
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    pypi_client: Annotated[PyPIServices, Depends(get_pypi_client)],
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
    scan = _lookup_package(name, version, session)
    inspector_url = _validate_inspector_url(name, version, body.inspector_url, scan.inspector_url)
    _validate_additional_information(body, scan)

    # If execution reaches here, we must have found a matching scan in our
    # database. Check if the package we want to report exists on PyPI.
    _validate_pypi(name, version, pypi_client)

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

        httpx.post(f"{mainframe_settings.reporter_url}/report/email", json=jsonable_encoder(report))
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

        httpx.post(f"{mainframe_settings.reporter_url}/report/{name}", json=jsonable_encoder(report))

    with session.begin():
        scan.reported_by = auth.subject
        scan.reported_at = dt.datetime.now(dt.timezone.utc)

    session.close()

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
