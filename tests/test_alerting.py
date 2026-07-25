import pytest
from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mainframe.endpoints.alerting import (
    get_alerting_configuration,
    update_alerting_configuration,
)
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import AlertingConfiguration
from mainframe.models.schemas import AlertingConfigurationUpdate


def test_get_alerting_configuration(
    db_session: Session,
    auth: AuthenticationData,
) -> None:
    response = get_alerting_configuration(db_session, auth)

    assert response.production_score_threshold == 8
    assert response.updated_by == "test-fixture"


def test_update_alerting_configuration(
    db_session: Session,
    auth: AuthenticationData,
) -> None:
    response = update_alerting_configuration(
        AlertingConfigurationUpdate(production_score_threshold=12),
        db_session,
        auth,
    )

    assert response.production_score_threshold == 12
    assert response.updated_by == auth.subject
    with db_session.begin():
        configuration = db_session.scalar(select(AlertingConfiguration))
    assert configuration is not None
    assert configuration.production_score_threshold == 12
    assert configuration.updated_by == auth.subject


def test_missing_alerting_configuration_returns_service_unavailable(
    db_session: Session,
    auth: AuthenticationData,
) -> None:
    with db_session.begin():
        db_session.execute(delete(AlertingConfiguration))

    with pytest.raises(HTTPException) as error:
        get_alerting_configuration(db_session, auth)

    assert error.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
