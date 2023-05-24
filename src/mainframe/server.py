import asyncio
from contextlib import asynccontextmanager
from os import getenv
from typing import Annotated
from unittest.mock import MagicMock

import aiohttp
from fastapi import Depends, FastAPI
from letsbuilda.pypi import PyPIServices
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mainframe.database import async_session, get_db
from mainframe.endpoints import routers
from mainframe.models.orm import Rule
from mainframe.models.schemas import ServerMetadata
from mainframe.rules import Rules, fetch_rules


async def sync_rules(*, http_session: aiohttp.ClientSession, session: AsyncSession):
    rules = await fetch_rules(http_session)
    session.add_all(Rule(name=rule_name) for rule_name in rules.rules)
    try:
        await session.commit()
    except IntegrityError:
        # Ignore rules that already exist in the database
        pass


@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Load the state for the app"""

    http_session = aiohttp.ClientSession()
    pypi_client = PyPIServices(http_session)
    rules = await fetch_rules(http_session)

    if getenv("env") == "test":
        fut: asyncio.Future[MagicMock] = asyncio.Future()
        fut.set_result(MagicMock(return_value=MagicMock()))
        pypi_client.get_package_metadata = MagicMock(return_value=fut)
        pypi_client.get_package_metadata.return_value.urls = [MagicMock(url=None), MagicMock(url=None)]

    app_.state.rules = rules
    app_.state.http_session = http_session
    app_.state.pypi_client = pypi_client

    session = async_session()
    await sync_rules(http_session=http_session, session=session)
    await session.close()

    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root_route() -> ServerMetadata:
    rules: Rules = app.state.rules
    return ServerMetadata(
        server_commit=getenv("GIT_SHA", "development"),
        rules_commit=rules.rules_commit,
    )


@app.post("/update-rules/")
async def update_rules(session: Annotated[AsyncSession, Depends(get_db)]):
    """Update the rules"""
    rules = await fetch_rules(app.state.http_session)
    app.state.rules = rules

    await sync_rules(http_session=app.state.http_session, session=session)


for router in routers:
    app.include_router(router)
