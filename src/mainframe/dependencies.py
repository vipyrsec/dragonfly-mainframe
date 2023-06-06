from functools import cache
from typing import Annotated

from fastapi import Depends
from msgraph.core import GraphClient

from mainframe.authorization_header_elements import get_bearer_token
from mainframe.custom_exceptions import PermissionDeniedException
from mainframe.json_web_token import JsonWebToken
from mainframe.utils.microsoft import build_ms_graph_client


@cache
def get_ms_graph_client() -> GraphClient:
    return build_ms_graph_client()


def validate_token(token: Annotated[str, Depends(get_bearer_token)]):
    return JsonWebToken(token).validate()


class PermissionsValidator:
    def __init__(self, required_permissions: list[str]):
        self.required_permissions = required_permissions

    def __call__(self, token: Annotated[str, Depends(validate_token)]):
        token_permissions = token.get("permissions")
        token_permissions_set = set(token_permissions)
        required_permissions_set = set(self.required_permissions)

        if not required_permissions_set.issubset(token_permissions_set):
            raise PermissionDeniedException
