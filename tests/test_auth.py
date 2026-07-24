import datetime as dt
import io
import json
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
from mainframe.json_web_token import (
    AuthenticationData,
    JsonWebToken,
    RateLimitedPyJWKClient,
    get_jwks_client,
)
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

RSA_JWK = {
    "alg": "RS256",
    "e": "AQAB",
    "key_ops": ["verify"],
    "kty": "RSA",
    "n": (
        "l0eCRGISml5-UdK6GTEYkrVXZlvTdWVdWkp-UoM-IXsXeqAwTSd6j8VNmeABWsAp"
        "XeXZ2KgGrPvl_ZQLCDDLY2r1X5Oex8BSQSUGUsw1dO-ekZ9_p0ygjWGzVsUqJZwxx"
        "JBOTVJ_weGxlNHGWKGe7ET0akZIWJMSeU7oKLJh6evd6AUc0MG0eTQfD-bOPCVk32"
        "JyvSWpXY5XUUCWotlzLbuNANhSC85ziZWdgZIKTtrC_EdnhlEfEAmmGOz7Ymfnp_N"
        "4ergE8LC_0Xo4i6I5roGBpPieYxjOq9Z_-be9mnOb1ZJAVAi_NcGHH0XzTYMfgVpm"
        "Ki3kG6cK77DS8NP5LQ"
    ),
    "use": "sig",
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
    monkeypatch.setattr("mainframe.json_web_token.get_jwks_client", Mock(return_value=jwks_client))
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


def test_get_jwks_client_is_cached(monkeypatch: pytest.MonkeyPatch):
    get_jwks_client.cache_clear()
    jwks_client = Mock()
    constructor = Mock(return_value=jwks_client)
    monkeypatch.setattr("mainframe.json_web_token.RateLimitedPyJWKClient", constructor)

    try:
        assert get_jwks_client("https://access.example.test/certs") is jwks_client
        assert get_jwks_client("https://access.example.test/certs") is jwks_client
    finally:
        get_jwks_client.cache_clear()

    constructor.assert_called_once_with("https://access.example.test/certs")


def test_unknown_kid_cannot_force_jwks_refresh(monkeypatch: pytest.MonkeyPatch):
    jwk_set = {"keys": [{**RSA_JWK, "kid": "cloudflare-key"}]}
    jwks_client = RateLimitedPyJWKClient("https://access.example.test/certs")

    def fetch_jwks(_request: object, *, timeout: float, context: object) -> io.BytesIO:
        del timeout, context
        return io.BytesIO(json.dumps(jwk_set).encode())

    fetch = Mock(side_effect=fetch_jwks)
    monkeypatch.setattr("jwt.jwks_client.urllib.request.urlopen", fetch)
    header_segment = "eyJhbGciOiJSUzI1NiIsImtpZCI6InVua25vd24ta2V5In0"
    payload_segment = "e30"
    token = f"{header_segment}.{payload_segment}."

    for _ in range(2):
        with pytest.raises(jwt.exceptions.PyJWKClientError):
            jwks_client.get_signing_key_from_jwt(token)

    assert fetch.call_count == 2


def test_signing_key_rotation_gets_one_bounded_refresh(monkeypatch: pytest.MonkeyPatch):
    old_jwk = {**RSA_JWK, "kid": "old-key"}
    new_jwk = {**old_jwk, "kid": "new-key"}
    jwk_sets = iter([{"keys": [old_jwk]}, {"keys": [old_jwk, new_jwk]}])
    jwks_client = RateLimitedPyJWKClient("https://access.example.test/certs")

    def fetch_jwks(_request: object, *, timeout: float, context: object) -> io.BytesIO:
        del timeout, context
        return io.BytesIO(json.dumps(next(jwk_sets)).encode())

    fetch = Mock(side_effect=fetch_jwks)
    monkeypatch.setattr("jwt.jwks_client.urllib.request.urlopen", fetch)
    header_segment = "eyJhbGciOiJSUzI1NiIsImtpZCI6Im5ldy1rZXkifQ"
    payload_segment = "e30"
    token = f"{header_segment}.{payload_segment}."

    signing_key = jwks_client.get_signing_key_from_jwt(token)

    assert signing_key.key_id == "new-key"
    assert fetch.call_count == 2


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (jwt.exceptions.PyJWKClientConnectionError("JWKS unavailable"), UnableCredentialsException),
        (jwt.exceptions.PyJWKClientError("unknown key"), BadCredentialsException),
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
    monkeypatch.setattr("mainframe.json_web_token.get_jwks_client", Mock(return_value=jwks_client))

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


def test_authentication_can_be_overridden_only_in_tests(
    app_without_auth: FastAPI,
    auth: AuthenticationData,
):
    override = app_without_auth.dependency_overrides[validate_token]
    assert override() == auth


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
