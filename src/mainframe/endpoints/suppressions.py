import datetime as dt
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Suppression
from mainframe.models.schemas import (
    SuppressionCreate,
    SuppressionDeleteResponse,
    SuppressionResponse,
    SuppressionUpdate,
)

router = APIRouter(prefix="/packages/{package_name}", tags=["suppressions"])


class SuppressionPath:
    """The nested identity of one suppression resource."""

    def __init__(
        self,
        package_name: str,
        package_version: str,
        suppression_id: uuid.UUID,
    ) -> None:
        self.package_name = package_name
        self.package_version = package_version
        self.suppression_id = suppression_id


def _normalize_package_name(package_name: str) -> str:
    """Return the normalized package name defined by PEP 503."""
    return re.sub(r"[-_.]+", "-", package_name).lower()


def _get_suppression(
    session: Session,
    *,
    package_name: str,
    package_version: str,
    suppression_id: uuid.UUID,
) -> Suppression:
    suppression = session.scalar(
        select(Suppression).where(
            Suppression.suppression_id == suppression_id,
            Suppression.package_name == _normalize_package_name(package_name),
            Suppression.package_version == package_version,
        )
    )
    if suppression is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Suppression not found.",
        )
    return suppression


@router.get("/suppressions")
def list_package_suppressions(
    package_name: str,
    session: Annotated[Session, Depends(get_db)],
    _auth: Annotated[AuthenticationData, Depends(validate_token)],
) -> list[SuppressionResponse]:
    """List every suppression for a package across all versions."""
    with session.begin():
        suppressions = session.scalars(
            select(Suppression)
            .where(Suppression.package_name == _normalize_package_name(package_name))
            .order_by(Suppression.package_version, Suppression.created_at, Suppression.suppression_id)
        ).all()
        return [SuppressionResponse.from_db(suppression) for suppression in suppressions]


@router.post(
    "/versions/{package_version}/suppressions",
    status_code=status.HTTP_201_CREATED,
)
def create_suppression(
    package_name: str,
    package_version: str,
    body: SuppressionCreate,
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
) -> SuppressionResponse:
    """Create an independently addressable suppression."""
    suppression = Suppression(
        package_name=_normalize_package_name(package_name),
        package_version=package_version,
        rules=body.rules,
        created_by=auth.subject,
        updated_by=auth.subject,
    )
    with session.begin():
        session.add(suppression)
        session.flush()
        return SuppressionResponse.from_db(suppression)


@router.get("/versions/{package_version}/suppressions/{suppression_id}")
def get_suppression(
    path: Annotated[SuppressionPath, Depends()],
    session: Annotated[Session, Depends(get_db)],
    _auth: Annotated[AuthenticationData, Depends(validate_token)],
) -> SuppressionResponse:
    """Get one suppression by its stable identifier."""
    with session.begin():
        return SuppressionResponse.from_db(
            _get_suppression(
                session,
                package_name=path.package_name,
                package_version=path.package_version,
                suppression_id=path.suppression_id,
            )
        )


@router.patch("/versions/{package_version}/suppressions/{suppression_id}")
def update_suppression(
    path: Annotated[SuppressionPath, Depends()],
    body: SuppressionUpdate,
    session: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthenticationData, Depends(validate_token)],
) -> SuppressionResponse:
    """Replace the rule corpus for one suppression."""
    with session.begin():
        suppression = _get_suppression(
            session,
            package_name=path.package_name,
            package_version=path.package_version,
            suppression_id=path.suppression_id,
        )
        suppression.rules = body.rules
        suppression.updated_at = dt.datetime.now(dt.UTC)
        suppression.updated_by = auth.subject
        session.flush()
        return SuppressionResponse.from_db(suppression)


@router.delete("/versions/{package_version}/suppressions/{suppression_id}")
def delete_suppression(
    path: Annotated[SuppressionPath, Depends()],
    session: Annotated[Session, Depends(get_db)],
    _auth: Annotated[AuthenticationData, Depends(validate_token)],
) -> SuppressionDeleteResponse:
    """Delete one suppression by its stable identifier."""
    with session.begin():
        suppression = _get_suppression(
            session,
            package_name=path.package_name,
            package_version=path.package_version,
            suppression_id=path.suppression_id,
        )
        session.delete(suppression)
    return SuppressionDeleteResponse(deleted=1)


@router.delete("/versions/{package_version}/suppressions")
def delete_version_suppressions(
    package_name: str,
    package_version: str,
    session: Annotated[Session, Depends(get_db)],
    _auth: Annotated[AuthenticationData, Depends(validate_token)],
) -> SuppressionDeleteResponse:
    """Delete every suppression for one package version."""
    with session.begin():
        deleted_ids = session.scalars(
            delete(Suppression)
            .where(
                Suppression.package_name == _normalize_package_name(package_name),
                Suppression.package_version == package_version,
            )
            .returning(Suppression.suppression_id)
        ).all()
    return SuppressionDeleteResponse(deleted=len(deleted_ids))
