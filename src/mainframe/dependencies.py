from functools import cache
from typing import Annotated

import aiohttp
from fastapi import Depends
from letsbuilda.pypi import PyPIServices
from msgraph.core import GraphClient

from utils.microsoft import build_ms_graph_client


async def get_http_session() -> aiohttp.ClientSession:
    http_session = aiohttp.ClientSession()
    return http_session


def get_pypi_client(http_session: Annotated[aiohttp.ClientSession, Depends(get_http_session)]) -> PyPIServices:
    return PyPIServices(http_session)


@cache
def get_ms_graph_client() -> GraphClient:
    return build_ms_graph_client()
