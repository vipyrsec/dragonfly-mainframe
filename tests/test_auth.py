from typing import cast
from unittest.mock import Mock

import pytest
from starlette.requests import Request

from mainframe.authorization_header_elements import (
    AuthorizationHeaderElements,
    get_authorization_header_elements,
    get_bearer_token,
)
from mainframe.custom_exceptions import (
    BadCredentialsException,
    RequiresAuthenticationException,
)


def test_get_authorization_header_elements():
    expected = AuthorizationHeaderElements(
        authorization_scheme="Bearer",
        bearer_token="test.bearer.token",
        are_valid=True,
    )

    assert get_authorization_header_elements("Bearer test.bearer.token") == expected


@pytest.mark.parametrize("inp", ["Bearer token extra", "Bearer"])
def test_invalid_authorization_header_elements(inp: str):
    with pytest.raises(BadCredentialsException):
        get_authorization_header_elements(inp)


def test_get_bearer_token(monkeypatch: pytest.MonkeyPatch):
    request = cast("Request", Mock(spec=Request))
    monkeypatch.setattr(request, "headers", {"Authorization": "Bearer token"})
    assert get_bearer_token(request) == "token"


def test_nonexistent_credentials(monkeypatch: pytest.MonkeyPatch):
    request = cast("Request", Mock(spec=Request))
    monkeypatch.setattr(request, "headers", {})
    with pytest.raises(RequiresAuthenticationException):
        get_bearer_token(request)


def test_invalid_credentials(monkeypatch: pytest.MonkeyPatch):
    request = cast("Request", Mock(spec=Request))
    monkeypatch.setattr(request, "headers", {"Authorization": "notbearer token"})
    with pytest.raises(BadCredentialsException):
        get_bearer_token(request)
