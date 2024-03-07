import datetime as dt
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from letsbuilda.pypi import PyPIServices
from letsbuilda.pypi.exceptions import PackageNotFoundError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import get_pypi_client, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan
from mainframe.models.schemas import (
    EmailReport,
    Error,
    ObservationReport,
    ReportPackageBody,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


router = APIRouter(tags=["report"])


def lookup_package(name: str, version: str, session: Session) -> Scan:
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

    query = select(Scan).where(Scan.name == name).options(selectinload(Scan.rules))
    scans = session.scalars(query).all()

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

    scan = session.scalar(query.where(Scan.version == version))
    if scan is None:
        error = HTTPException(
            404, detail=f"Package `{name}` has records in the database, but none with version `{version}`"
        )
        log.error(f"No version {version} for package {name} in database", tag="invalid_version")
        raise error

    return scan


def build_email_report(body: ReportPackageBody) -> EmailReport:
    """
    Builds an `EmailReport` from a `ReportPackageBody`.

    Returns:
        A valid `EmailReport`.

    Raises:
        HTTPException(400): Missing required fields.
        HTTPException(404): The package was not found on PyPI, the package was
            not found in the database, or the specified name and version was not
            found in the database.
        HTTPException(409): The package was already reported.
    """

    return EmailReport(
        name=body.name,
        version=body.version,
        rules_matched=rules_matched,
        recipient=body.recipient,
        inspector_url=inspector_url,
        additional_information=additional_information,
    )


def build_observation_report(body: ReportPackageBody) -> ObservationReport:
    """
    Builds an `ObservationReport` from a `ReportPackageBody`.

    Returns:
        A valid `ObservationReport`.

    Raises:
        HTTPException(400): Missing required fields.
        HTTPException(404): The package was not found on PyPI, the package was
            not found in the database, or the specified name and version was not
            found in the database.
        HTTPException(409): The package was already reported.
    """
    ...


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
    `inspector_url` is omitted, then it will be that of the most malicious file
    scanned (that is, the file with the highest aggregate yara weight score).
    If the `additional_information` is omitted, the final e-mail sent to the
    destination address will read "No user description provided." If either of
    these fields are included, they override the default value in the database.

    If the package has successfully been scanned (that is, it is in
    a `FINISHED` state), and it has been determined NOT to be malicious (that
    is, it has no matched rules), then you must provide `inspector_url` AND
    `additional_information`.
    """

    name = body.name
    version = body.version

    log = logger.bind(package={"name": name, "version": version})

    # Check our database first to avoid unnecessarily using PyPI API.
    scan = lookup_package(name, version, session)

    inspector_url = body.inspector_url or scan.inspector_url
    if inspector_url is None:
        error = HTTPException(
            400,
            detail=f"inspector_url is a required field as package `{body.name}@{body.version}` inspector_url column as null.",
        )
        log.error("Missing inspector_url field", error_message=error.detail, tag="missing_inspector_url")
        raise error

    if body.additional_information is None:
        if len(scan.rules) == 0:
            error = HTTPException(
                400,
                detail=(
                    f"additional_information is a required field as package "
                    f"`{name}@{version}` has no matched rules in the database"
                ),
            )
            log.error(
                "Missing additional_information field", error_message=error.detail, tag="missing_additional_information"
            )
            raise error

        if body.use_email is True:
            error = HTTPException(400, detail="additional_information is required when using Observation API")
            log.error(
                "Missing additional_information field", error_message=error.detail, tag="missing_additional_information"
            )
            raise error

    # If execution reaches here, we must have found a matching scan in our
    # database. Check if the package we want to report exists on PyPI.
    try:
        pypi_client.get_package_metadata(name, version)
    except PackageNotFoundError:
        error = HTTPException(404, detail=f"Package `{name}@{version}` was not found on PyPI")
        log.error(f"Package {name}@{version} was not found on PyPI", tag="package_not_found_pypi")
        raise error

    rules_matched: list[str] = []
    rules_matched.extend(rule.name for rule in scan.rules)

    if body.use_email is True:
        ...
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
    else:
        ...

    scan.reported_by = auth.subject
    scan.reported_at = dt.datetime.now(dt.timezone.utc)
    session.commit()
