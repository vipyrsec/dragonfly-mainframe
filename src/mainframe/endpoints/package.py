from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.models.orm import Scan
from mainframe.models.schemas import Error

router = APIRouter(tags=["package"])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@router.get(
    "/package",
    responses={400: {"model": Error, "description": "Invalid parameter combination."}},
    dependencies=[Depends(validate_token)],
)
def lookup_package_info(
    session: Annotated[Session, Depends(get_db)],
    name: Optional[str] = None,
    version: Optional[str] = None,
):
    """
    Lookup information on scanned packages based on name or version.

    Args:
        name: The name of the package.
        version: The version of the package.
        session: DB session.
    """

    nn_name = name is not None
    nn_version = version is not None

    log = logger.bind(
        parameters={
            "name": name,
            "version": version,
        }
    )

    query = select(Scan).options(selectinload(Scan.rules))
    if nn_name:
        query = query.where(Scan.name == name)
    if nn_version:
        query = query.where(Scan.version == version)

    data = session.scalars(query)

    log.info("Package information queried")
    return data.all()
