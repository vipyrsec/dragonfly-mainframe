from typing import Annotated

import aiohttp
from fastapi import Depends
from letsbuilda.pypi import PyPIServices


async def get_http_session() -> aiohttp.ClientSession:
    http_session = aiohttp.ClientSession()
    return http_session


def get_pypi_client(http_session: Annotated[aiohttp.ClientSession, Depends(get_http_session)]) -> PyPIServices:
    return PyPIServices(http_session)
