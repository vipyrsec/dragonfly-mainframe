from functools import cache
from typing import Annotated

import httpx
from fastapi import Depends, Request

from mainframe.access_token import get_access_token
from mainframe.json_web_token import AuthenticationData, JsonWebToken
from mainframe.pypi import PyPIClient
from mainframe.rules import Rules


@cache
def get_pypi_client() -> PyPIClient:
    http_client = httpx.Client()
    return PyPIClient(http_client)


def get_httpx_client(request: Request) -> httpx.Client:
    return request.app.state.http_session


def get_rules(request: Request) -> Rules:
    return request.app.state.rules


def validate_token(token: Annotated[str, Depends(get_access_token)]) -> AuthenticationData:
    return JsonWebToken(token).validate()
