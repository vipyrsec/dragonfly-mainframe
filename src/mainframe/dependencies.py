from datetime import datetime, timedelta
from functools import cache
from typing import Annotated

from fastapi import Depends
from msgraph.core import GraphClient  # type: ignore

from mainframe.authorization_header_elements import get_bearer_token
from mainframe.custom_exceptions import PermissionDeniedException
from mainframe.json_web_token import AuthenticationData, JsonWebToken
from mainframe.utils.microsoft import build_ms_graph_client  # type: ignore


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
