from dataclasses import dataclass
from datetime import datetime
from typing import Any

import jwt

from mainframe.constants import mainframe_settings
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
    grant_type: str

    @classmethod
    def from_dict(cls, data: dict[Any, Any]):
        return AuthenticationData(
            issuer=data["iss"],
            subject=data["sub"],
            audience=data["aud"],
            issued_at=datetime.fromtimestamp(data["iat"]),
            expires_at=datetime.fromtimestamp(data["exp"]),
            grant_type=data["gty"],
        )


@dataclass
class JsonWebToken:
    """Perform JSON Web Token (JWT) validation using PyJWT"""

    jwt_access_token: str
    auth0_issuer_url: str = f"https://{mainframe_settings.auth0_domain}/"
    auth0_audience: str = mainframe_settings.auth0_audience
    algorithm: str = "RS256"
    jwks_uri: str = f"{auth0_issuer_url}.well-known/jwks.json"

    def validate(self) -> AuthenticationData:
        try:
            jwks_client = jwt.PyJWKClient(self.jwks_uri)
            jwt_signing_key = jwks_client.get_signing_key_from_jwt(self.jwt_access_token).key
            payload = jwt.decode(
                self.jwt_access_token,
                jwt_signing_key,
                algorithms=self.algorithm,
                audience=self.auth0_audience,
                issuer=self.auth0_issuer_url,
            )
        except jwt.exceptions.PyJWKClientError:
            raise UnableCredentialsException
        except jwt.exceptions.InvalidTokenError:
            raise BadCredentialsException
        return AuthenticationData.from_dict(payload)
