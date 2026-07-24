from starlette.requests import Request as StarletteRequest

from mainframe.custom_exceptions import RequiresAuthenticationException


def get_access_token(request: StarletteRequest) -> str:
    if access_token := request.headers.get("Cf-Access-Jwt-Assertion"):
        return access_token
    raise RequiresAuthenticationException
