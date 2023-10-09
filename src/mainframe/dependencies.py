from datetime import datetime, timedelta
from functools import cache
from typing import Annotated

import httpx
from fastapi import Depends, Request
from letsbuilda.pypi import PyPIServices
from msgraph.core import GraphClient

from mainframe.authorization_header_elements import get_bearer_token
from mainframe.custom_exceptions import PermissionDeniedException
from mainframe.json_web_token import AuthenticationData, JsonWebToken
from mainframe.rules import Rules
from mainframe.utils.microsoft import build_ms_graph_client


@cache
def get_ms_graph_client() -> GraphClient:  # type: ignore
    return build_ms_graph_client()  # type: ignore


@cache
def get_pypi_client() -> PyPIServices:
    session = httpx.Client()
    return PyPIServices(session)


def get_rules(request: Request) -> Rules:
    return request.app.state.rules


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

        # type: ignore
        if not required_permissions_set.issubset(token_permissions_set):
            raise PermissionDeniedException
