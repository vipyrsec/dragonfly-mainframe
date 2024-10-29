from collections.abc import Iterable, Sequence
import datetime as dt
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi_pagination import Page, Params
from fastapi_pagination.ext.sqlalchemy import paginate  # type: ignore
from letsbuilda.pypi import Package as PyPIPackage, PyPIServices  # type: ignore
from letsbuilda.pypi.exceptions import PackageNotFoundError
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy.orm import Session, joinedload

from mainframe.database import get_db
from mainframe.dependencies import get_pypi_client, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import DownloadURL, Rule, Scan, Status
from mainframe.models.schemas import (
    Error,
    Package,
    PackageScanResult,
    PackageScanResultFail,
    PackageSpecifier,
    QueuePackageResponse,
)

from mainframe.metrics import packages_ingested, packages_in_queue, packages_fail, packages_success

router = APIRouter(tags=["package"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@router.put(
    "/package",
    responses={
        400: {"model": Error},
        409: {"model": Error},
    },
)
def submit_results(
    result: PackageScanResult | PackageScanResultFail,
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
):
    name = result.name
    version = result.version

    with session.begin():
        scan = session.scalar(
            select(Scan).where(Scan.name == name).where(Scan.version == version).options(joinedload(Scan.rules))
        )

    log = logger.bind(package={"name": name, "version": version})

    if scan is None:
        error = HTTPException(404, f"Package `{name}@{version}` not found in database.")
        log.error(
            f"Package {name}@{version} not found in database", error_message=error.detail, tag="package_not_found_db"
        )
        raise error

    if scan.status == Status.FINISHED:
        error = HTTPException(409, f"Package `{name}@{version}` is already in a FINISHED state.")
        log.error(
            f"Scan {name}@{version} already in a FINISHED state", error_message=error.detail, tag="already_finished"
        )
        packages_fail.inc()
        packages_in_queue.dec()
        raise error

    with session, session.begin():
        if isinstance(result, PackageScanResultFail):
            scan.status = Status.FAILED
            scan.fail_reason = result.reason

            session.commit()
            return

        scan.status = Status.FINISHED
        scan.finished_at = dt.datetime.now(dt.timezone.utc)
        scan.inspector_url = result.inspector_url
        scan.score = result.score
        scan.finished_by = auth.subject
        scan.commit_hash = result.commit

        # These are the rules that already have an entry in the database
        rules = session.scalars(select(Rule).where(Rule.name.in_(result.rules_matched))).all()
        rule_names = {rule.name for rule in rules}
        scan.rules.extend(rules)

        # These are the rules that had to be created
        new_rules = [Rule(name=rule_name) for rule_name in result.rules_matched if rule_name not in rule_names]
        scan.rules.extend(new_rules)

    log.info(
        "Scan results submitted",
        package={
            "name": name,
            "version": version,
            "status": scan.status,
            "finished_at": scan.finished_at,
            "inspector_url": result.inspector_url,
            "score": result.score,
            "finished_by": auth.subject,
            "existing_rules": rule_names,
            "created_rules": [rule.name for rule in new_rules],
        },
        tag="scan_submitted",
    )

    packages_success.inc()
    packages_in_queue.dec()


@router.get(
    "/package",
    responses={400: {"model": Error, "description": "Invalid parameter combination."}},
    dependencies=[Depends(validate_token)],
)
def lookup_package_info(
    session: Annotated[Session, Depends(get_db)],
    since: Optional[int] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    page: Optional[int] = None,
    size: Optional[int] = None,
) -> Page[Package] | Sequence[Package]:
    """
    Lookup information on scanned packages based on name, version, or time
    scanned. If multiple packages are returned, they are ordered with the most
    recently queued package first.

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
        log.debug(
            "Invalid parameter combination",
            tag="invalid_parameter_combination",
        )
        raise HTTPException(status_code=400)

    query = select(Scan).order_by(Scan.queued_at.desc()).options(joinedload(Scan.rules), joinedload(Scan.download_urls))
    if nn_name:
        query = query.where(Scan.name == name)
    if nn_version:
        query = query.where(Scan.version == version)
    if nn_since:
        query = query.where(Scan.finished_at >= dt.datetime.fromtimestamp(since, tz=dt.timezone.utc))

    with session, session.begin():
        if page and size:
            params = Params(page=page, size=size)
            return paginate(
                session, query, params=params, transformer=lambda items: [Package.from_db(item) for item in items]
            )
        data = session.scalars(query).unique()
        return [Package.from_db(result) for result in data]


def _deduplicate_packages(packages: list[PackageSpecifier], session: Session) -> set[tuple[str, str]]:
    name_ver = {(p.name, p.version) for p in packages}
    scalars = session.scalars(select(Scan).where(tuple_(Scan.name, Scan.version).in_(name_ver)))
    return name_ver - {(scan.name, scan.version) for scan in scalars.all()}


def _get_packages_metadata(pypi_client: PyPIServices, packages_to_check: set[tuple[str, str]]) -> Iterable[PyPIPackage]:
    if not packages_to_check:
        return

    def _get_package_metadata(package: tuple[str, str]) -> Optional[PyPIPackage]:
        try:
            return pypi_client.get_package_metadata(*package)
        except PackageNotFoundError:
            return

    # IO-bound, so these threads won't take up much CPU. Just spawn as many as
    # we need to send all requests at once. We avoid the
    # `len(packages_to_check) == 0` case by returning early above
    with ThreadPoolExecutor(max_workers=len(packages_to_check)) as tpe:
        yield from filter(None, tpe.map(_get_package_metadata, packages_to_check))


@router.post(
    "/batch/package",
    responses={
        409: {"model": Error},
        404: {"model": Error},
    },
)
def batch_queue_package(
    packages: list[PackageSpecifier],
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    pypi_client: Annotated[PyPIServices, Depends(get_pypi_client)],
):
    with session, session.begin():
        packages_to_check = _deduplicate_packages(packages, session)

        for package_metadata in _get_packages_metadata(pypi_client, packages_to_check):
            scan = Scan(
                name=package_metadata.title,
                version=package_metadata.releases[0].version,
                status=Status.QUEUED,
                queued_by=auth.subject,
                download_urls=[
                    DownloadURL(url=distribution.url) for distribution in package_metadata.releases[0].distributions
                ],
            )

            session.add(scan)

            packages_ingested.inc()
            packages_in_queue.inc()


@router.post(
    "/package",
    responses={
        409: {"model": Error},
        404: {"model": Error},
    },
)
def queue_package(
    package: PackageSpecifier,
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
    pypi_client: Annotated[PyPIServices, Depends(get_pypi_client)],
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

    try:
        package_metadata = pypi_client.get_package_metadata(name, version)
    except PackageNotFoundError:
        error = HTTPException(404, detail=f"Package {name}@{version} was not found on PyPI")
        log.error(
            f"Package {name}@{version} was not found on PyPI", error_message=error.detail, tag="package_not_found_pypi"
        )
        raise error

    new_package = Scan(
        name=name,
        version=version,
        status=Status.QUEUED,
        queued_by=auth.subject,
        download_urls=[
            DownloadURL(url=distribution.url) for distribution in package_metadata.releases[0].distributions
        ],
    )

    try:
        with session, session.begin():
            session.add(new_package)
    except IntegrityError:
        log.warn(f"Package {name}@{version} already queued for scanning.", tag="already_queued")
        raise HTTPException(409, f"Package {name}@{version} is already queued for scanning")

    log.info(
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

    packages_ingested.inc()
    packages_in_queue.inc()

    return QueuePackageResponse(id=str(new_package.scan_id))
