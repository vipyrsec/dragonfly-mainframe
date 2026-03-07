import datetime as dt
from types import SimpleNamespace

import jwt
import pytest

from mainframe.custom_exceptions import UnableCredentialsException
from mainframe.json_web_token import JsonWebToken, get_jwks_client


@pytest.fixture(autouse=True)
def clear_jwks_client_cache() -> None:
    get_jwks_client.cache_clear()


def test_get_jwks_client_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    created_clients: list[str] = []

    class FakeJWKClient:
        def __init__(self, uri: str) -> None:
            created_clients.append(uri)
            self.uri = uri

    monkeypatch.setattr("mainframe.json_web_token.jwt.PyJWKClient", FakeJWKClient)

    first_client = get_jwks_client("https://issuer.example/.well-known/jwks.json")
    second_client = get_jwks_client("https://issuer.example/.well-known/jwks.json")

    assert first_client is second_client
    assert created_clients == ["https://issuer.example/.well-known/jwks.json"]


def test_json_web_token_reuses_cached_jwks_client(monkeypatch: pytest.MonkeyPatch) -> None:
    constructor_calls = 0

    class FakeJWKClient:
        def __init__(self, _uri: str) -> None:
            nonlocal constructor_calls
            constructor_calls += 1

        def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
            return SimpleNamespace(key="signing-key")

    def fake_decode(
        _token: str,
        _key: str,
        *,
        algorithms: str,
        audience: str,
        issuer: str,
    ) -> dict[str, str | int]:
        assert algorithms == "RS256"
        assert audience == "vipyrsec-api"
        assert issuer == "https://issuer.example/"
        return {
            "iss": issuer,
            "sub": "auth0|user-123",
            "aud": audience,
            "iat": int(dt.datetime(2026, 3, 7, tzinfo=dt.UTC).timestamp()),
            "exp": int(dt.datetime(2026, 3, 7, 1, tzinfo=dt.UTC).timestamp()),
        }

    monkeypatch.setattr("mainframe.json_web_token.jwt.PyJWKClient", FakeJWKClient)
    monkeypatch.setattr("mainframe.json_web_token.jwt.decode", fake_decode)

    token = JsonWebToken(
        jwt_access_token="header.payload.signature",
        auth0_issuer_url="https://issuer.example/",
        auth0_audience="vipyrsec-api",
        jwks_uri="https://issuer.example/.well-known/jwks.json",
    )

    first_payload = token.validate()
    second_payload = token.validate()

    assert first_payload.subject == "auth0|user-123"
    assert second_payload.subject == "auth0|user-123"
    assert constructor_calls == 1


def test_json_web_token_raises_unable_credentials_on_jwks_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeJWKClient:
        def __init__(self, _uri: str) -> None:
            pass

        def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
            msg = "timed out fetching JWKS"
            raise jwt.exceptions.PyJWKClientError(msg)

    monkeypatch.setattr("mainframe.json_web_token.jwt.PyJWKClient", FakeJWKClient)

    token = JsonWebToken(
        jwt_access_token="header.payload.signature",
        auth0_issuer_url="https://issuer.example/",
        auth0_audience="vipyrsec-api",
        jwks_uri="https://issuer.example/.well-known/jwks.json",
    )

    with pytest.raises(UnableCredentialsException):
        token.validate()
