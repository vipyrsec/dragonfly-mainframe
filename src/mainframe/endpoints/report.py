from letsbuilda.pypi import PyPIServices
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from mainframe.models.orm import Package
from mainframe.models.schemas import Error, PackageSpecifier
from textwrap import dedent
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from mainframe.database import get_db
import datetime as dt
from mainframe.server import get_pypi_client
from utils.mailer import send_email
from utils.microsoft import build_ms_graph_client
from utils.pypi import file_path_from_inspector_url

graph_client = build_ms_graph_client()


def send_report_email(
    *,
    package_name: str,
    package_version: str,
    inspector_url: str,
    additional_information: str | None,
    rules_matched: List[str],
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
        Additional Information: {additional_information or 'No user description provided'}
        Yara rules matched: {', '.join(rules_matched) or 'No rules matched'}
    """
    content = dedent(content)

    send_email(
        graph_client,
        sender="system@mantissecurity.org",
        subject="Test email",
        content=content,
        to_recipients=["robinjefferson123@gmail.com"],
        cc_recipients=[],
        bcc_recipients=[],
    )


class ReportPackageBody(PackageSpecifier):
    inspector_url: Optional[str]
    additional_information: Optional[str]


router = APIRouter()


@router.post(
    "/report",
    responses={
        409: {"model": Error},
        400: {"model": Error},
    },
)
async def report_package(
    body: ReportPackageBody,
    session: AsyncSession = Depends(get_db),
    pypi_client: PyPIServices = Depends(get_pypi_client),
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

    If the package has successfully been scanned (that is, it is in a FINISHED state),
    and it has been determined to be malicious, then neither inspector_url nor additional_information
    is required. If the inspector_url is omitted, then it will be that of the most malicious file scanned
    (that is, the file with the highest aggregate yara weight score).
    If the `additional_information` is omitted, the final e-mail sent to the destination address will read
    "No user description provided."
    If either of these fields are included, they override the default value in the database.

    If the package has successfully been scanned (that is, it is in a FINISHED state),
    and it has been determined NOT to be malicious (that is, it has no matched rules),
    then you must provide inspector_url AND additional_information.

    In all cases, the API will provide information on what fields it is missing and why.
    This way, clients may retry the request with the proper information provided
    if they had not done so properly the first time.
    """

    name = body.name
    version = body.version

    try:
        package_metadata = await pypi_client.get_package_metadata(name, version)
    except KeyError:
        raise HTTPException(404, detail=f"Package `{name}@{version}` was not found on PyPI")

    version = package_metadata.info.version

    row = await session.scalar(
        select(Package)
        .where(Package.name == name)
        .where(Package.version == version)
        .options(selectinload(Package.rules))
    )

    inspector_url: str | None = None
    additional_information: str | None = None
    rules_matched: list[str] = []

    if row is None:
        raise HTTPException(404, detail=f"A record for package `{name}@{version}` does not exist in the database")

    if row.reported_at is not None:
        raise HTTPException(409, detail=f"Package `{name}@{version}` has already been reported")

    if body.inspector_url is None:
        if row.inspector_url is None:
            raise HTTPException(
                400,
                detail=f"inspector_url is a required field as package `{name}@{version}` inspector_url column as null.",
            )

        inspector_url = row.inspector_url
    else:
        inspector_url = body.inspector_url

    if body.additional_information is None:
        if len(row.rules) == 0:
            raise HTTPException(
                400,
                detail=(
                    f"additional_information is a required field as package "
                    f"`{name}@{version}` has no matched rules in the database"
                ),
            )

        rules_matched.extend(rule.name for rule in row.rules)

    additional_information = body.additional_information

    send_report_email(
        package_name=name,
        package_version=version,
        inspector_url=inspector_url,
        additional_information=additional_information,
        rules_matched=rules_matched,
    )

    row.reported_at = dt.datetime.utcnow()
    await session.commit()