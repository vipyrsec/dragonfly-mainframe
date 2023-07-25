import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.models.orm import Scan
from mainframe.models.schemas import (
    GetScansResponse,
    MaliciousPackage,
    PackageSpecifier,
)

router = APIRouter(tags=["scans"])


@router.get("/scans", dependencies=[Depends(validate_token)])
async def get_scans(session: Annotated[AsyncSession, Depends(get_db)], since: int) -> GetScansResponse:
    scalars = await session.scalars(
        select(Scan)
        .where(Scan.finished_at >= dt.datetime.fromtimestamp(since, tz=dt.timezone.utc))
        .options(selectinload(Scan.rules))
    )

    all_scans = scalars.all()

    malicious_packages: list[MaliciousPackage] = []
    for scan in all_scans:
        if scan.score is None:
            continue

        if scan.score < mainframe_settings.score_threshold:
            continue

        if scan.inspector_url is None:
            continue

        malicious_package = MaliciousPackage(
            name=scan.name,
            version=scan.version,
            score=scan.score,
            inspector_url=scan.inspector_url,
            rules=[rule.name for rule in scan.rules],
        )

        malicious_packages.append(malicious_package)

    return GetScansResponse(
        all_scans=[PackageSpecifier(name=scan.name, version=scan.version) for scan in all_scans],
        malicious_packages=malicious_packages,
    )
