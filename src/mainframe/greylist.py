from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from mainframe.models.orm import Package, Status
from mainframe.models.schemas import PackageScanResult


async def greylist_scan(
    result: PackageScanResult,
    session: Annotated[AsyncSession, Depends(get_db)],
):
    """Check if the rules we matched are the same as the last scan """
    if results.rules == []
        return False

    row = await session.scalars(
        select(Package.rules)
        .where(Package.name == name)
        .where(Package.status == Status.FINISHED)
        .order_by(Package.finished_at.desc())
        .first()
    )

    if row.rules == result.rules:
        return True

    return False
