import datetime as dt
from textwrap import dedent
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from letsbuilda.pypi import PyPIServices
from msgraph.core import GraphClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import get_ms_graph_client, validate_token
from mainframe.greylist import greylist_scan
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Scan
from mainframe.models.schemas import Error, PackageSpecifier
from mainframe.utils.mailer import send_email
from mainframe.utils.pypi import file_path_from_inspector_url

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


def send_report_email(
    graph_client: GraphClient,  # type: ignore
    *,
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
        sender="system@mantissecurity.org",
        subject=f"Automated PyPI Malware Report: {package_name}@{package_version}",
        content=content,
        to_recipients=[mainframe_settings.email_recipient],
        cc_recipients=[],
        bcc_recipients=list(mainframe_settings.bcc_recipients),
    )


class ReportPackageBody(PackageSpecifier):
    inspector_url: Optional[str]
    additional_information: Optional[str]


router = APIRouter(tags=["report"])


@router.post(
    "/report",
    responses={
        409: {"model": Error},
        400: {"model": Error},
    },
)
async def report_package(
    body: ReportPackageBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    graph_client: Annotated[GraphClient, Depends(get_ms_graph_client)],  # type: ignore
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    request: Request,
):
    """
    Report a package by sending an email to PyPI with the appropriate format

    Packages that do not exist in the database (e.g it was not queued yet)
    cannot be reported.

    Packages that do not exist on PyPI cannot be reported.

    Packages that have already been reported cannot be reported.

    While the `inspector_url` and `additional_information` endpoints are optional in the schema,
    the API requires you to provide them in certain cases. Some of those are outlined below.

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

    pypi_client: PyPIServices = request.app.state.pypi_client
    try:
        package_metadata = await pypi_client.get_package_metadata(name, version)
    except KeyError:
        error = HTTPException(404, detail=f"Package `{name}@{version}` was not found on PyPI")
        await log.aerror(
            f"Package {name}@{version} was not found on PyPI", error_message=error.detail, tag="package_not_found_pypi"
        )
        raise error

    version = package_metadata.info.version
    log = logger.bind(package={"name": name, "version": version})

    query = select(Scan).where(Scan.name == name).options(selectinload(Scan.rules))

    rows = (await session.scalars(query)).fetchall()

    inspector_url: str | None = None
    additional_information: str | None = None
    rules_matched: list[str] = []

    if not rows:
        error = HTTPException(404, detail=f"No records for package `{name}` were found in the database")
        await log.aerror(
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
            await log.aerror(
                "Only one version of a package allowed to be reported at a time",
                error_message=error.detail,
                tag="multiple_versions_prohibited",
            )
            raise error

    row = await session.scalar(query.where(Scan.version == version))
    if row is None:
        error = HTTPException(
            404, detail=f"Package `{name}` has records in the database, but none with version `{version}`"
        )
        await log.aerror(
            f"No version {version} for package {name} in database", error_message=error.detail, tag="invalid_version"
        )
        raise error

    if body.inspector_url is None:
        if row.inspector_url is None:
            error = HTTPException(
                400,
                detail=f"inspector_url is a required field as package `{name}@{version}` inspector_url column as null.",
            )
            await log.aerror("Missing inspector_url field", error_message=error.detail, tag="missing_inspector_url")
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
            await log.aerror(
                "Missing additional_information field", error_message=error.detail, tag="missing_additional_information"
            )
            raise error

        rules_matched.extend(rule.name for rule in row.rules)

    if greylist_scan(name, row.rule_names, session) is True:
        raise HTTPException(
            409,
            detail=(
                f"A previous version ({row.version}) of this package matched "
                f"all of the same rules. It is improbable that this new version "
                f"has become malicious without deviations in rule flagging"
            ),
        )

    additional_information = body.additional_information

    send_report_email(
        graph_client,  # type: ignore
        package_name=name,
        package_version=version,
        inspector_url=inspector_url,
        additional_information=additional_information,
        rules_matched=rules_matched,
    )

    await log.ainfo(
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
    await session.commit()
