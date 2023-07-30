from datetime import datetime, timedelta
from typing import Any, Optional

import jwt
from fastapi import Form, HTTPException, Request
from fastapi.openapi.models import OAuthFlowClientCredentials, OAuthFlows
from fastapi.security.oauth2 import OAuth2
from fastapi.security.utils import get_authorization_scheme_param
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session
from starlette.status import HTTP_401_UNAUTHORIZED

from mainframe.constants import mainframe_settings
from mainframe.models.orm import APIClient


class OAuth2ClientCredentialsRequestForm:
    """
    Expect OAuth2 client credentials as form request parameters

    This is a dependency class, modeled after OAuth2PasswordRequestForm and similar.
    Use it like:

        @app.post("/login")
        def login(form_data: OAuth2ClientCredentialsRequestForm = Depends()):
            data = form_data.parse()
            print(data.client_id)
            for scope in data.scopes:
                print(scope)
            return data

    It creates the following Form request parameters in your endpoint:
    grant_type: the OAuth2 spec says it is required and MUST be the fixed string "client_credentials".
    scope: Several scopes (each one a string) separated by spaces. Currently unused.
    client_id: string. OAuth2 recommends sending the client_id and client_secret (if any)
    client_secret: string. OAuth2 recommends sending the client_id and client_secret (if any)
    """

    def __init__(
        self,
        grant_type: str = Form(regex="^(client_credentials|refresh_token)$"),
        scope: str = Form(""),
        client_id: Optional[str] = Form(None),
        client_secret: Optional[str] = Form(None),
    ):
        self.grant_type = grant_type
        self.scopes = scope.split()
        self.client_id = client_id
        self.client_secret = client_secret


class OAuth2ClientCredentials(OAuth2):
    """
    Implement OAuth2 client_credentials workflow.

    This is modeled after the OAuth2PasswordBearer and OAuth2AuthorizationCodeBearer
    classes from FastAPI, but sets auto_error to True to avoid uncovered branches.
    See https://github.com/tiangolo/fastapi/issues/774 for original implementation,
    and to check if FastAPI added a similar class.

    See RFC 6749 for details of the client credentials authorization grant.
    """

    def __init__(
        self,
        tokenUrl: str,
        scheme_name: Optional[str] = None,
        scopes: Optional[dict[str, str]] = None,
    ):
        scopes = scopes or {}
        flows = OAuthFlows(clientCredentials=OAuthFlowClientCredentials(tokenUrl=tokenUrl, scopes=scopes))
        super().__init__(flows=flows, scheme_name=scheme_name, auto_error=True)

    async def __call__(self, request: Request) -> Optional[str]:
        authorization = request.headers.get("Authorization")

        scheme, token = get_authorization_scheme_param(authorization)

        if not authorization or scheme.lower() != "bearer":
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return token


oauth2_scheme = OAuth2ClientCredentials(tokenUrl="oauth/token")

SECRET_KEY = mainframe_settings.SECRET_KEY
ALGORITHM = mainframe_settings.JWT_SIGNING_ALGORITHM


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expires_delta = expires_delta or timedelta(minutes=15)
    exp = int((datetime.utcnow() + expires_delta).timestamp())
    to_encode.update(dict(exp=exp))
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    return encoded_jwt


pwd_context = CryptContext(schemes=["argon2"])


def verify_secret(plain_secret: str, hashed_secret: str) -> bool:
    """Verify the secret, using a constant time equality check."""

    return pwd_context.verify(plain_secret, hashed_secret)


def hash_secret(plain_secret: str) -> str:
    """Hash the password, using the pre-configured CryptContext."""
    return pwd_context.hash(plain_secret)


def create_client(
    session: Session,
    *,
    client_id: str,
    client_secret: str,
    username: str,
    admin: bool = False,
):
    """Create a client in the database. Hashes their secret."""

    api_client = APIClient(
        client_id=client_id,
        hashed_secret=hash_secret(client_secret),
        username=username,
        admin=admin,
    )

    session.add(api_client)
    session.commit()


def get_client_by_id(
    session: Session,
    *,
    client_id: str,
) -> Optional[APIClient]:
    """Find a client by their ID"""

    return session.scalar(select(APIClient).where(APIClient.client_id == client_id))


def get_client_by_access_token(
    session: Session,
    *,
    access_token: str,
) -> Optional[APIClient]:
    """Find a client by their access token"""

    decoded_jwt = jwt.decode(access_token, key=SECRET_KEY, algorithms=[ALGORITHM])
    client_id: str = decoded_jwt["sub"]
    return get_client_by_id(session, client_id=client_id)


def get_all_clients(session: Session) -> list[APIClient]:
    """Get all clients"""

    return list(session.scalars(select(APIClient)).all())


def update_client(
    session: Session,
    client_id: str,
    *,
    new_client_id: Optional[str] = None,
    new_client_secret: Optional[str] = None,
    new_username: Optional[str] = None,
    new_admin: Optional[bool] = None,
) -> None:
    """
    Update a client's information.

    Raises a `sqlalchemy.exc.NoResultFound` if `client_id` was not
    found in the database.
    """

    api_client = get_client_by_id(session, client_id=client_id)
    if api_client is None:
        raise NoResultFound()

    if new_client_id:
        api_client.client_id = new_client_id

    if new_client_secret:
        api_client.hashed_secret = hash_secret(new_client_secret)

    if new_username:
        api_client.username = new_username

    if new_admin:
        api_client.admin = new_admin

    session.commit()
