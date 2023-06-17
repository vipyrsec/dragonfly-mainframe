from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mainframe.database import get_db
from mainframe.models.orm import Package, Status


async def greylist_scan(
    package_name: str,
    rules_matched: list[str],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> bool:
    """Check if the rules we matched are the same as the last scan."""

    if len(rules_matched) == 0:
        return False

    row = (
        await session.scalars(
            select(Package.rules)
            .where(Package.name == package_name)
            .where(Package.status == Status.FINISHED)
            .order_by(Package.finished_at.desc())
        )
    ).first()

    return row == rules_matched
