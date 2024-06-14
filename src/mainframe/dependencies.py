from datetime import datetime, timedelta
from functools import cache
from typing import Annotated

import httpx
from fastapi import Depends, Request
from letsbuilda.pypi import PyPIServices

from mainframe.authorization_header_elements import get_bearer_token
from mainframe.custom_exceptions import PermissionDeniedException
from mainframe.json_web_token import AuthenticationData, JsonWebToken
from mainframe.rules import Rules


@cache
def get_pypi_client() -> PyPIServices:
    http_client = httpx.Client()
    return PyPIServices(http_client)


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
