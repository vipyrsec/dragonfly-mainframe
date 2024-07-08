from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.models.orm import Scan, Status
from mainframe.models.schemas import StatsResponse

router = APIRouter(tags=["stats"])


def _get_package_ingest(session: Session) -> int:
    scalar_result = session.scalars(
        select(func.count()).select_from(Scan).where(Scan.queued_at > datetime.now(timezone.utc) - timedelta(hours=24))
    )
    return scalar_result.one()


def _get_average_scan_time(session: Session) -> float:
    scalar_result = session.scalars(
        select(func.avg(Scan.finished_at - Scan.pending_at))
        .where(Scan.pending_at.is_not(None))
        .where(Scan.finished_at.is_not(None))
        .where(Scan.queued_at > datetime.now(timezone.utc) - timedelta(hours=24))
    )

    return scalar_result.one().total_seconds()


def _get_failed_packages(session: Session) -> int:
    scalar_result = session.scalars(
        select(func.count())
        .select_from(Scan)
        .where(Scan.status == Status.FAILED)
        .where(Scan.queued_at > datetime.now(timezone.utc) - timedelta(hours=24))
    )

    return scalar_result.one()


@router.get("/stats", dependencies=[Depends(validate_token)])
def get_stats(session: Annotated[Session, Depends(get_db)]) -> StatsResponse:
    return StatsResponse(
        ingested=_get_package_ingest(session),
        average_scan_time=_get_average_scan_time(session),
        failed=_get_failed_packages(session),
    )
