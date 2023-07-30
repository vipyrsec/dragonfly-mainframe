from datetime import datetime, timedelta
from functools import cache
from typing import Annotated

from fastapi import Depends, HTTPException
from msgraph.core import GraphClient
from sqlalchemy.orm import Session
from starlette.status import HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND

from mainframe.auth import get_client_by_access_token, oauth2_scheme
from mainframe.authorization_header_elements import get_bearer_token
from mainframe.custom_exceptions import PermissionDeniedException
from mainframe.database import get_db
from mainframe.json_web_token import AuthenticationData, JsonWebToken
from mainframe.models.orm import APIClient
from mainframe.utils.microsoft import build_ms_graph_client


@cache
def get_ms_graph_client() -> GraphClient:  # type: ignore
    return build_ms_graph_client()  # type: ignore


def validate_token(token: Annotated[str, Depends(get_bearer_token)]) -> AuthenticationData:
    return JsonWebToken(token).validate()


def validate_token_override():
    return AuthenticationData(
        issuer="DEVELOPMENT ISSUER",
        subject="DEVELOPMENT SUBJECT",
        audience="DEVELOPMENT AUDIENCE",
        issued_at=datetime.now() - timedelta(seconds=10),
        expires_at=datetime.now() + timedelta(seconds=10),
        grant_type="DEVELOPMENT GRANT TYPE",
    )


class PermissionsValidator:
    def __init__(self, required_permissions: list[str]):
        self.required_permissions = required_permissions

    def __call__(self, data: Annotated[AuthenticationData, Depends(validate_token)]):
        token_permissions = data.permissions  # type: ignore
        token_permissions_set = set(token_permissions)  # type: ignore
        required_permissions_set = set(self.required_permissions)

        if not required_permissions_set.issubset(token_permissions_set):  # type: ignore
            raise PermissionDeniedException


def check_admin(
    session: Annotated[Session, Depends(get_db)],
    access_token: Annotated[str, Depends(oauth2_scheme)],
):
    """
    Checks if the given access token has admin privileges. Intended for use in FastAPI decorators.

    Throws an `HTTPException` with status code 403 FORBIDDEN if the user is not an administrator
    Throws an `HTTPException` with status code 404 NOT FOUND if the user could not be found
    Returns `None` if the user is an administrator.
    """

    client = get_client_by_access_token(session, access_token=access_token)
    if client is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="Client not found")

    if client.admin is False:
        raise HTTPException(HTTP_403_FORBIDDEN, detail="Administrator privileges are required for this path")

    return None


def get_current_client(
    session: Annotated[Session, Depends(get_db)],
    access_token: Annotated[str, Depends(oauth2_scheme)],
) -> APIClient:
    """
    Uses the access_token to get the currently logged in client.

    Throws an `HTTPException` with status code 404 NOT FOUND if the user could not be found
    Returns the `APIClient` that is associated with this access token.
    """

    client = get_client_by_access_token(session, access_token=access_token)
    if client is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="Client not found")

    return client
