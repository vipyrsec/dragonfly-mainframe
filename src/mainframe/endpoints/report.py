import datetime as dt
from textwrap import dedent
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from letsbuilda.pypi import PyPIServices
from letsbuilda.pypi.exceptions import PackageNotFoundError
from msgraph.core import GraphClient
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import get_ms_graph_client, get_pypi_client, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan
from mainframe.models.schemas import Error, ReportPackageBody
from mainframe.utils.mailer import send_email
from mainframe.utils.pypi import file_path_from_inspector_url

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


def send_report_email(
    graph_client: GraphClient,  # type: ignore
    *,
    recipient: str,
    package_name: str,
    package_version: str,
    inspector_url: str,
    additional_information: str | None,
    rules_matched: list[str],
):
    if additional_information is None and len(rules_matched) == 0:
        raise ValueError("Cannot report a package that matched 0 rules without additional information")

    content = f"""
        PyPI Malicious Package Report
        -
        Package Name: {package_name}
        Version: {package_version}
        File path: {file_path_from_inspector_url(inspector_url)}
        Inspector URL: {inspector_url}
        Additional Information: {additional_information or "No user description provided"}
        Yara rules matched: {", ".join(rules_matched) or "No rules matched"}
    """
    content = dedent(content)

    send_email(
        graph_client,  # type: ignore
        subject=f"Automated PyPI Malware Report: {package_name}@{package_version}",
        content=content,
        reply_to_recipients=[mainframe_settings.email_reply_to],
        sender=mainframe_settings.email_sender,
        to_recipients=[recipient],
        bcc_recipients=list(mainframe_settings.bcc_recipients),
    )


router = APIRouter(tags=["report"])


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
    graph_client: Annotated[GraphClient, Depends(get_ms_graph_client)],  # type: ignore
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    pypi_client: Annotated[PyPIServices, Depends(get_pypi_client)],
):
    """
    Report a package by sending an email to `recipient` address with the appropriate format

    Packages that do not exist in the database (e.g it was not queued yet)
    cannot be reported.

    Packages that do not exist on PyPI cannot be reported.

    Packages that have already been reported cannot be reported.

    While the `inspector_url` and `additional_information` fields are optional in the schema,
    the API requires you to provide them in certain cases. Some of those are outlined below.

    If the `recipient` field is not omitted, then that specified email address will be used
    as the recipient to the report email. If omitted, it will be whatever is configured as
    the default on the server. This is most likely `security@pypi.org` unless it is
    overriden in the server configuration.

    `inspector_url` and `additional_information` both must be provided if
    the package being reported is in a `QUEUED` or `PENDING` state. That is, the package
    has not yet been scanned and therefore has no records for `inspector_url`
    or any matched rules

    If the package has successfully been scanned (that is, it is in a `FINISHED` state),
    and it has been determined to be malicious, then neither `inspector_url` nor `additional_information`
    is required. If the `inspector_url` is omitted, then it will be that of the most malicious file scanned
    (that is, the file with the highest aggregate yara weight score).
    If the `additional_information` is omitted, the final e-mail sent to the destination address will read
    "No user description provided."
    If either of these fields are included, they override the default value in the database.

    If the package has successfully been scanned (that is, it is in a `FINISHED` state),
    and it has been determined NOT to be malicious (that is, it has no matched rules),
    then you must provide `inspector_url` AND `additional_information`.

    In all cases, the API will provide information on what fields it is missing and why.
    This way, clients may retry the request with the proper information provided
    if they had not done so properly the first time.
    """

    name = body.name
    version = body.version

    log = logger.bind(package={"name": name, "version": version})

    try:
        package_metadata = pypi_client.get_package_metadata(name, version)
    except PackageNotFoundError:
        error = HTTPException(404, detail=f"Package `{name}@{version}` was not found on PyPI")
        log.debug(f"Package {name}@{version} was not found on PyPI", tag="package_not_found_pypi")
        raise error

    version = package_metadata.releases[0].version
    log = logger.bind(package={"name": name, "version": version})

    query = select(Scan).where(Scan.name == name).options(selectinload(Scan.rules))

    rows = session.scalars(query).all()

    inspector_url: str | None = None
    additional_information: str | None = None
    rules_matched: list[str] = []

    if not rows:
        error = HTTPException(404, detail=f"No records for package `{name}` were found in the database")
        log.error(
            f"No records for package {name} found in database", error_message=error.detail, tag="package_not_found_db"
        )
        raise error

    for row in rows:
        if row.reported_at is not None:
            error = HTTPException(
                409,
                detail=(
                    f"Only one version of a package may be reported at a time. "
                    f"(`{row.name}@{row.version}` was already reported)"
                ),
            )
            log.error(
                "Only one version of a package allowed to be reported at a time",
                error_message=error.detail,
                tag="multiple_versions_prohibited",
            )
            raise error

    row = session.scalar(query.where(Scan.version == version))
    if row is None:
        error = HTTPException(
            404, detail=f"Package `{name}` has records in the database, but none with version `{version}`"
        )
        log.debug(f"No version {version} for package {name} in database", tag="invalid_version")
        raise error

    if body.inspector_url is None:
        if row.inspector_url is None:
            error = HTTPException(
                400,
                detail=f"inspector_url is a required field as package `{name}@{version}` inspector_url column as null.",
            )
            log.error("Missing inspector_url field", error_message=error.detail, tag="missing_inspector_url")
            raise error

        inspector_url = row.inspector_url
    else:
        inspector_url = body.inspector_url

    if body.additional_information is None:
        if len(row.rules) == 0:
            error = HTTPException(
                400,
                detail=(
                    f"additional_information is a required field as package "
                    f"`{name}@{version}` has no matched rules in the database"
                ),
            )
            log.debug("Missing additional_information field", tag="missing_additional_information")
            raise error

    rules_matched.extend(rule.name for rule in row.rules)

    additional_information = body.additional_information

    send_report_email(
        graph_client,  # type: ignore
        recipient=body.recipient or mainframe_settings.email_recipient,
        package_name=name,
        package_version=version,
        inspector_url=inspector_url,
        additional_information=additional_information,
        rules_matched=rules_matched,
    )

    log.info(
        "Sent report",
        email_data={
            "package_name": name,
            "package_version": version,
            "inspector_url": inspector_url,
            "additional_information": additional_information,
            "rules_matched": rules_matched,
        },
        reported_by=auth.subject,
    )

    row.reported_by = auth.subject
    row.reported_at = dt.datetime.now(dt.timezone.utc)
    session.commit()
