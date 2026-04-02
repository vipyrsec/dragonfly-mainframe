from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from mainframe.database import get_db
from mainframe.models.orm import SuppressedPackage, Scan
from mainframe.models.schemas import SuppressedPackageResponse

router = APIRouter(tags=["suppression"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@router.put(
    path="/suppress",
    responses={
        404: {"description": "No scan found with the specified id"},
        200: {"description": "Package has been suppressed"},
    },
)
def suppress_package(
    package_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    """
    Suppress a package.

    Args:
        package_id: The id of the package to suppress.
        session: Database session.

    Raises:
        HTTPException: 404 Not Found if no scan was found with the specified id.
    """
    scan = session.scalar(select(Scan).where(Scan.scan_id == package_id))
    if not scan:
        raise HTTPException(status_code=404, detail=f"No scan found with id {package_id}")

    log = logger.bind(package_name=scan.name, scan_id=package_id)
    already_suppressed = session.scalar(
        select(SuppressedPackage).join(Scan, SuppressedPackage.scan_id == Scan.scan_id).where(Scan.name == scan.name)
    )

    with session.begin():
        if already_suppressed:
            if newest_scan := session.scalar(
                select(Scan).where(Scan.name == scan.name).order_by(Scan.finished_at.desc())
            ):
                already_suppressed.scan_id = str(newest_scan.scan_id)
                log.info("Updated suppression entry", new_scan_id=newest_scan.scan_id)
            else:
                log.error("No scan found for package", package_name=scan.name)
                raise HTTPException(status_code=500, detail=f"Could not find scan for package {scan.name}")
        else:
            suppressed_package = SuppressedPackage(scan_id=package_id)
            session.add(suppressed_package)
            log.info("Package has been suppressed")


@router.get(
    path="/suppressed",
    responses={
        200: {"description": "List of suppressed packages"},
    },
    response_model=list[SuppressedPackageResponse],
)
def get_suppressed_packages(
    session: Annotated[Session, Depends(get_db)],
    package_name: Optional[str] = None,
) -> list[SuppressedPackageResponse]:
    """
    Get a list of suppressed packages with their details.

    Args:
        session: Database session.
        package_name: Optional name of the package to filter by.

    Returns:
        A list of suppressed package details.
    """
    query = (
        select(Scan)
        .join(SuppressedPackage, SuppressedPackage.scan_id == Scan.scan_id)
        .options(joinedload(Scan.rules))
        .order_by(Scan.name)
    )

    if package_name:
        query = query.where(Scan.name == package_name)

    scans = session.scalars(query).all()

    return [
        SuppressedPackageResponse(
            name=scan.name,
            version=scan.version,
            scan_id=str(scan.scan_id),
            suppressed_at=str(scan.finished_at),
            rules=[rule.name for rule in scan.rules],
        )
        for scan in scans
    ]


@router.delete(
    path="/unsuppress",
    responses={
        404: {"description": "No suppressed package found with the specified name"},
        200: {"description": "Package has been unsuppressed"},
    },
)
def unsuppress_package(
    package_name: str,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    """
    Remove suppression for a package.

    Args:
        package_name: The name of the package to unsuppress.
        session: Database session.

    Raises:
        HTTPException: 404 Not Found if no suppressed package was found.
    """
    suppressed_package = session.scalar(
        select(SuppressedPackage).join(Scan, SuppressedPackage.scan_id == Scan.scan_id).where(Scan.name == package_name)
    )
    if not suppressed_package:
        raise HTTPException(status_code=404, detail=f"No suppressed package found with name {package_name}")

    with session.begin():
        session.delete(suppressed_package)
        logger.bind(package_name=package_name).info("Package has been unsuppressed")
