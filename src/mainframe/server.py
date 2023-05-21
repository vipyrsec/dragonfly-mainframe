from contextlib import asynccontextmanager
from os import getenv
from typing import Annotated

import aiohttp
from fastapi import Depends, FastAPI
from letsbuilda.pypi import PyPIServices
from sqlalchemy.ext.asyncio import AsyncSession

from mainframe.database import get_db
from mainframe.endpoints import routers
from mainframe.models.orm import Rule
from mainframe.models.schemas import ServerMetadata
from mainframe.rules import Rules, fetch_rules


@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Load the state for the app"""
    http_session = aiohttp.ClientSession()
    pypi_client = PyPIServices(http_session)
    rules = await fetch_rules(http_session)

    app_.state.rules = rules
    app_.state.http_session = http_session
    app_.state.pypi_client = pypi_client

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

    session.add_all(Rule(name=rule_name) for rule_name in rules.rules)
    await session.commit()


for router in routers:
    app.include_router(router)
