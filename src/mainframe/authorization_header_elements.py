from typing import NamedTuple

from starlette.requests import Request as StarletteRequest

from mainframe.custom_exceptions import (
    BadCredentialsException,
    RequiresAuthenticationException,
)


class AuthorizationHeaderElements(NamedTuple):
    authorization_scheme: str
    bearer_token: str
    are_valid: bool


def get_authorization_header_elements(
    authorization_header: str,
) -> AuthorizationHeaderElements:
    try:
        authorization_scheme, bearer_token = authorization_header.split()
    except ValueError as err:
        raise BadCredentialsException from err
    else:
        valid = authorization_scheme.lower() == "bearer" and bool(bearer_token.strip())
        return AuthorizationHeaderElements(authorization_scheme, bearer_token, valid)


def get_bearer_token(request: StarletteRequest) -> tuple[str, str]:
    cf_authorization_header = request.headers.get("CF_Authorization")
    if cf_authorization_header:
        return ("cf", cf_authorization_header)

    authorization_header = request.headers.get("Authorization")
    if authorization_header:
        authorization_header_elements = get_authorization_header_elements(authorization_header)
        if authorization_header_elements.are_valid:
            return ("auth0", authorization_header_elements.bearer_token)
        raise BadCredentialsException
    raise RequiresAuthenticationException
