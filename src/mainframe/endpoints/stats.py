from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.models.orm import Scan
from mainframe.models.schemas import StatsResponse

router = APIRouter(tags=["stats"])


def _get_package_ingest(session: Session) -> int:
    scalar_result = session.scalars(select(func.count()).select_from(Scan))
    return scalar_result.one()


@router.get("/stats", dependencies=[Depends(validate_token)])
def get_stats(session: Annotated[Session, Depends(get_db)]) -> StatsResponse:
    return StatsResponse(
        ingested=_get_package_ingest(session),
    )
