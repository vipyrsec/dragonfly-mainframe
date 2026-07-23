import datetime as dt
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import Mock

import anyio
import httpx
import jwt
import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.types import Scope

from mainframe.access_token import get_access_token
from mainframe.constants import cf_access_settings
from mainframe.custom_exceptions import (
    BadCredentialsException,
    RequiresAuthenticationException,
    UnableCredentialsException,
)
from mainframe.dependencies import validate_token
from mainframe.json_web_token import AuthenticationData, JsonWebToken
from mainframe.server import app

PROTECTED_ROUTES = {
    ("GET", "/package"),
    ("GET", "/reported-packages"),
    ("GET", "/rules"),
    ("POST", "/batch/package"),
    ("POST", "/jobs"),
    ("POST", "/package"),
    ("POST", "/report"),
    ("POST", "/update-rules/"),
    ("PUT", "/package"),
}


def _request(headers: dict[str, str]) -> Request:
    scope = cast(
        "Scope",
        {
            "type": "http",
            "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        },
    )
    return Request(scope)


def test_get_access_token():
    assert get_access_token(_request({"Cf-Access-Jwt-Assertion": "token"})) == "token"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer legacy-token"},
        {"Cf-Access-Jwt-Assertion": ""},
    ],
)
def test_get_access_token_rejects_missing_or_legacy_credentials(headers: dict[str, str]):
    with pytest.raises(RequiresAuthenticationException):
        get_access_token(_request(headers))


def test_validate_cloudflare_access_token(monkeypatch: pytest.MonkeyPatch):
    now = dt.datetime.now(dt.UTC)
    payload = {
        "iss": cf_access_settings.team_domain,
        "sub": "service-token-id",
        "aud": cf_access_settings.audience,
        "iat": int((now - dt.timedelta(seconds=10)).timestamp()),
        "exp": int((now + dt.timedelta(minutes=5)).timestamp()),
        "common_name": "dragonfly-client-staging",
    }
    signing_key = Mock(key="public-key")
    jwks_client = Mock()
    jwks_client.get_signing_key_from_jwt.return_value = signing_key
    monkeypatch.setattr(jwt, "PyJWKClient", Mock(return_value=jwks_client))
    decode = Mock(return_value=payload)
    monkeypatch.setattr(jwt, "decode", decode)

    result = JsonWebToken("signed-token").validate()

    assert result == AuthenticationData(
        issuer=cf_access_settings.team_domain,
        subject="dragonfly-client-staging",
        audience=cf_access_settings.audience,
        issued_at=now.replace(microsecond=0) - dt.timedelta(seconds=10),
        expires_at=now.replace(microsecond=0) + dt.timedelta(minutes=5),
        grant_type=None,
    )
    jwks_client.get_signing_key_from_jwt.assert_called_once_with("signed-token")
    decode.assert_called_once_with(
        "signed-token",
        "public-key",
        audience=cf_access_settings.audience,
        issuer=cf_access_settings.team_domain,
        algorithms=["RS256"],
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (jwt.exceptions.PyJWKClientError("JWKS unavailable"), UnableCredentialsException),
        (jwt.exceptions.InvalidTokenError("invalid token"), BadCredentialsException),
    ],
)
def test_validate_cloudflare_access_token_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected: type[Exception],
):
    jwks_client = Mock()
    jwks_client.get_signing_key_from_jwt.side_effect = error
    monkeypatch.setattr(jwt, "PyJWKClient", Mock(return_value=jwks_client))

    with pytest.raises(expected):
        JsonWebToken("signed-token").validate()


def test_protected_route_inventory():
    openapi_paths = cast("dict[str, dict[str, object]]", app.openapi()["paths"])
    protected_routes = {
        (method.upper(), path)
        for path, path_item in openapi_paths.items()
        if path not in {"/", "/metrics"}
        for method in path_item
    }
    assert protected_routes == PROTECTED_ROUTES
    assert validate_token not in app.dependency_overrides


@pytest.mark.parametrize(
    ("headers", "detail"),
    [
        ({}, "Requires authentication"),
        ({"Authorization": "Bearer legacy-token"}, "Requires authentication"),
        ({"Cf-Access-Jwt-Assertion": "invalid-token"}, "Bad credentials"),
    ],
)
def test_every_protected_route_rejects_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    detail: str,
):
    @asynccontextmanager
    async def empty_lifespan(_app: FastAPI):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", empty_lifespan)
    if "Cf-Access-Jwt-Assertion" in headers:
        monkeypatch.setattr(JsonWebToken, "validate", Mock(side_effect=BadCredentialsException))

    async def assert_routes_reject_invalid_credentials() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mainframe.test") as client:
            for method, path in PROTECTED_ROUTES:
                response = await client.request(method, path, headers=headers)
                assert response.status_code == 401, (method, path, response.text)
                assert response.json() == {"detail": detail}

    anyio.run(assert_routes_reject_invalid_credentials)
