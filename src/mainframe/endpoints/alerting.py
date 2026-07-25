import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import AlertingConfiguration
from mainframe.models.schemas import (
    AlertingConfigurationResponse,
    AlertingConfigurationUpdate,
)

router = APIRouter(prefix="/alerting", tags=["alerting"])


def _get_configuration(session: Session) -> AlertingConfiguration:
    configuration = session.scalar(select(AlertingConfiguration).where(AlertingConfiguration.id == 1))
    if configuration is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alerting configuration is unavailable.",
        )
    return configuration


def _to_response(
    configuration: AlertingConfiguration,
) -> AlertingConfigurationResponse:
    return AlertingConfigurationResponse(
        production_score_threshold=configuration.production_score_threshold,
        updated_at=configuration.updated_at,
        updated_by=configuration.updated_by,
    )


@router.get("/configuration")
def get_alerting_configuration(
    session: Annotated[Session, Depends(get_db)],
    _auth: Annotated[AuthenticationData, Depends(validate_token)],
) -> AlertingConfigurationResponse:
    """Return the durable production alerting configuration."""
    with session.begin():
        return _to_response(_get_configuration(session))


@router.put("/configuration")
def update_alerting_configuration(
    body: AlertingConfigurationUpdate,
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
) -> AlertingConfigurationResponse:
    """Replace the mutable production alerting configuration."""
    with session.begin():
        configuration = _get_configuration(session)
        configuration.production_score_threshold = body.production_score_threshold
        configuration.updated_at = dt.datetime.now(dt.UTC)
        configuration.updated_by = auth.subject
        session.flush()
        return _to_response(configuration)
