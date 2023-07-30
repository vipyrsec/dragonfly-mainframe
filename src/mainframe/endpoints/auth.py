import binascii
from base64 import b64decode
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.orm import Session
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from mainframe.auth import (
    OAuth2ClientCredentialsRequestForm,
    create_access_token,
    create_client,
    get_all_clients,
    get_client_by_id,
    update_client,
    verify_secret,
)
from mainframe.constants import mainframe_settings
from mainframe.database import get_db
from mainframe.dependencies import check_admin, get_current_client
from mainframe.models.orm import APIClient
from mainframe.models.schemas import (
    CreateClientDTO,
    GetClientDTO,
    Token,
    UpdateClientDTO,
)

router = APIRouter(tags=["Authentication"])

token_scheme = HTTPBasic(auto_error=True)


@router.post("/oauth/token", summary="Get an access token")
def login(
    request: Request,
    form_data: Annotated[OAuth2ClientCredentialsRequestForm, Depends()],
    session: Annotated[Session, Depends(get_db)],
):
    failed_auth = HTTPException(HTTP_400_BAD_REQUEST, detail="Incorrect or invalid credentials")

    if form_data.client_id and form_data.client_secret:
        client_id = form_data.client_id
        client_secret = form_data.client_secret
    elif authorization_header := request.headers.get("Authorization"):
        scheme, param = get_authorization_scheme_param(authorization_header)
        if scheme.lower() != "basic":
            raise failed_auth

        try:
            data = b64decode(param).decode("ascii")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            raise failed_auth

        username, separator, password = data.partition(":")
        if not separator:
            raise failed_auth

        client_id = username
        client_secret = password
    else:
        raise failed_auth

    api_client = session.scalar(select(APIClient).where(APIClient.client_id == client_id))

    if api_client is None:
        raise failed_auth

    if verify_secret(client_secret, api_client.hashed_secret) is False:
        raise failed_auth

    expires_delta = timedelta(minutes=mainframe_settings.JWT_EXPIRES_DELTA_MINUTES)
    access_token = create_access_token(data=dict(sub=client_id, admin=api_client.admin), expires_delta=expires_delta)

    return Token(
        access_token=access_token, token_type="bearer", expires_in=mainframe_settings.JWT_EXPIRES_DELTA_MINUTES
    )


@router.post("/client", summary="Create a client", dependencies=[Depends(check_admin)])
def post_client(client: CreateClientDTO, session: Annotated[Session, Depends(get_db)]):
    try:
        create_client(
            session=session,
            client_id=client.client_id,
            client_secret=client.client_secret,
            username=client.username,
        )
    except IntegrityError:
        raise HTTPException(409, detail="Client already exists.")


@router.get("/clients/me", summary="Get currently logged in client")
def get_clients_me(
    client: Annotated[APIClient, Depends(get_current_client)],
) -> GetClientDTO:
    return GetClientDTO(
        client_id=client.client_id,
        username=client.username,
        admin=client.admin,
    )


@router.get("/clients/{client_id}", summary="Get client by ID", dependencies=[Depends(check_admin)])
def client_by_id(client_id: str, session: Annotated[Session, Depends(get_db)]) -> GetClientDTO:
    client = get_client_by_id(session, client_id=client_id)

    if client is None:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="client not found")

    return GetClientDTO(
        client_id=client.client_id,
        username=client.username,
        admin=client.admin,
    )


@router.get("/clients", summary="Get all clients", dependencies=[Depends(check_admin)])
def all_clients(session: Annotated[Session, Depends(get_db)]) -> list[GetClientDTO]:
    return [
        GetClientDTO(client_id=client.client_id, username=client.username, admin=client.admin)
        for client in get_all_clients(session)
    ]


@router.patch("/client/{client_id}", summary="Update a client", dependencies=[Depends(check_admin)])
def patch_client(client_id: str, payload: UpdateClientDTO, session: Annotated[Session, Depends(get_db)]):
    try:
        update_client(
            session,
            client_id,
            new_client_id=payload.client_id,
            new_client_secret=payload.client_secret,
            new_username=payload.username,
            new_admin=payload.admin,
        )
    except NoResultFound:
        raise HTTPException(HTTP_404_NOT_FOUND, detail="Client not found")
