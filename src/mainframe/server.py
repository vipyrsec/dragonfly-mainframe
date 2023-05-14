import os
import typing
from contextlib import asynccontextmanager

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI
from letsbuilda.pypi import PyPIServices
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .endpoints import job, package

load_dotenv()

engine = create_async_engine(os.getenv("DB_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432"))
async_session = async_sessionmaker(bind=engine, expire_on_commit=False)


@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Load the state for the app"""
    session = aiohttp.ClientSession()
    pypi_client = PyPIServices(session)
    app_.state.pypi_client = pypi_client

    yield


app = FastAPI(lifespan=lifespan)


async def get_pypi_client():
    pypi_client = typing.cast(PyPIServices, app.state.pypi_client)  # type: ignore
    yield pypi_client


app.include_router(package.router)
app.include_router(job.router)
