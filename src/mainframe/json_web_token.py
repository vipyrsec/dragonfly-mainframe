from dataclasses import dataclass
from datetime import datetime
from typing import Any

import jwt

from mainframe.constants import keycloak_settings
from mainframe.custom_exceptions import (
    BadCredentialsException,
    UnableCredentialsException,
)

@dataclass
class AuthenticationData:
    issuer: str
    subject: str
    audience: str
    issued_at: datetime
    expires_at: datetime

    @classmethod
    def from_dict(cls, data: dict[Any, Any]):
        return AuthenticationData(
            issuer=data["iss"],
            subject=data["sub"],
            audience=data["aud"],
            issued_at=datetime.fromtimestamp(data["iat"]),
            expires_at=datetime.fromtimestamp(data["exp"]),
        )


@dataclass
class JsonWebToken:
    """Perform JSON Web Token (JWT) validation using PyJWT"""

    jwt_access_token: str
    algorithm: str = "RS256"

    def validate(self) -> AuthenticationData:
        try:
            jwks_client = jwt.PyJWKClient(keycloak_settings.jwks_uri, headers={"User-Agent": "Dragonfly Mainframe"})
            jwt_signing_key = jwks_client.get_signing_key_from_jwt(self.jwt_access_token).key
            payload = jwt.decode(
                self.jwt_access_token,
                jwt_signing_key,
                algorithms=self.algorithm,  # type: ignore
                audience=keycloak_settings.audience,
                issuer=keycloak_settings.issuer_url,
            )
            print(payload)
        except jwt.exceptions.PyJWKClientError:
            raise UnableCredentialsException
        except jwt.exceptions.InvalidTokenError:
            raise BadCredentialsException
        return AuthenticationData.from_dict(payload)
