import datetime as dt
from dataclasses import dataclass
from functools import cache
from threading import Lock
from typing import Any, Self

import jwt

from mainframe.constants import cf_access_settings
from mainframe.custom_exceptions import (
    BadCredentialsException,
    UnableCredentialsException,
)


class CachedPyJWKClient(jwt.PyJWKClient):
    """Refresh the JWKS on a fixed schedule, independent of requested key IDs."""

    def __init__(self, uri: str, lifespan: float = 10.0) -> None:
        super().__init__(uri, lifespan=lifespan)
        self._cache_lock = Lock()

    def get_signing_key(self, kid: str) -> jwt.PyJWK:
        with self._cache_lock:
            signing_key = self.match_kid(self.get_signing_keys(), kid)

        if signing_key is None:
            message = "Unable to find a matching signing key"
            raise jwt.exceptions.PyJWKClientError(message)

        return signing_key


@cache
def get_jwks_client(jwks_uri: str) -> jwt.PyJWKClient:
    """Return a shared JWKS client with PyJWT's key-set cache."""
    return CachedPyJWKClient(jwks_uri)


@dataclass
class AuthenticationData:
    issuer: str
    subject: str
    audience: str
    issued_at: dt.datetime
    expires_at: dt.datetime
    grant_type: str | None

    @classmethod
    def from_dict(cls, data: dict[Any, Any]) -> Self:
        return cls(
            issuer=data["iss"],
            subject=data["sub"],
            audience=data["aud"],
            issued_at=dt.datetime.fromtimestamp(data["iat"], tz=dt.UTC),
            expires_at=dt.datetime.fromtimestamp(data["exp"], tz=dt.UTC),
            grant_type=data.get("gty"),
        )


@dataclass
class JsonWebToken:
    """Validate Cloudflare Access JSON Web Token using PyJWT."""

    jwt_access_token: str
    audience = cf_access_settings.audience
    jwks_uri = f"{cf_access_settings.team_domain}/cdn-cgi/access/certs"
    algorithm: str = "RS256"

    def validate(self) -> AuthenticationData:
        try:
            jwks_client = get_jwks_client(self.jwks_uri)
            jwt_signing_key = jwks_client.get_signing_key_from_jwt(self.jwt_access_token).key

            payload = jwt.decode(
                self.jwt_access_token,
                jwt_signing_key,
                audience=cf_access_settings.audience,
                issuer=cf_access_settings.team_domain,
                algorithms=[self.algorithm],
            )
        except jwt.exceptions.PyJWKClientConnectionError as err:
            raise UnableCredentialsException from err
        except (jwt.exceptions.PyJWKClientError, jwt.exceptions.InvalidTokenError) as err:
            raise BadCredentialsException from err

        auth_data = AuthenticationData.from_dict(payload)

        # Service tokens identify themselves with common_name; interactive
        # identities use email. Cloudflare always supplies sub as a fallback.
        auth_data.subject = payload.get("common_name") or payload.get("email") or payload["sub"]

        return auth_data
