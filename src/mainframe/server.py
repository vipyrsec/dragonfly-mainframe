import datetime as dt
import os
import typing
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional

import aiohttp
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from letsbuilda.pypi import PyPIServices
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Package, Status

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


async def get_db():
    session = async_session()
    try:
        yield session
    finally:
        await session.close()


@dataclass(frozen=True)
class PackageScanResult:
    most_malicious_file: Optional[str]
    score: int


@dataclass(frozen=True)
class Error:
    """Error"""

    detail: str


class QueuePackageBody(BaseModel):
    """
    name:  A str of the name of the package to be scanned
    version: An optional str of the package version to scan. If omitted, latest version is used
    """

    name: str
    version: Optional[str]


class QueuePackageResponse(BaseModel):
    id: str


@app.post(
    "/package",
    responses={
        409: {"model": Error},
        404: {"model": Error},
    },
)
async def queue_package(
    body: QueuePackageBody,
    session: AsyncSession = Depends(get_db),
    pypi_client: PyPIServices = Depends(get_pypi_client),
) -> QueuePackageResponse:
    """
    Queue a package to be scanned when the next runner is available

    Args:
        Body: Request body paramters
        session: Database session
        pypi_client: client instance used to interact with PyPI JSON API

    Returns:
        404: The given package and version combination was not found on PyPI
        409: The given package and version combination has already been queued
    """

    name = body.name
    version = body.version

    try:
        package_metadata = await pypi_client.get_package_metadata(name, version)
    except KeyError:
        raise HTTPException(404, detail=f"Package {name}@{version} was not found on PyPI")

    version = package_metadata.info.version  # Use latest version if not provided

    query = select(Package).where(Package.name == name).where(Package.version == version)
    package = await session.scalar(query)

    if package is not None:
        raise HTTPException(409, f"Package {name}@{version} is already queued for scanning")

    package = Package(
        name=name,
        version=version,
        status=Status.QUEUED,
    )

    session.add(package)
    await session.commit()

    return QueuePackageResponse(id=str(package.package_id))


@app.get("/package", responses={400: {"model": Error, "description": "Invalid parameter combination."}})
async def lookup_package_info(
    since: Optional[int] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    session: AsyncSession = Depends(get_db),
):
    """
    Lookup information on scanned packages based on name, version, or time scanned.

    Args:
        since: A int representing a Unix timestamp representing when to begin the search from.
        name: The name of the package.
        version: The version of the package.
        session: DB session.

    Only certain combinations of parameters are allowed. A query is valid if any of the following combinations are used:
        - `name` and `version`: Return the package with name `name` and version `version`, if it exists.
        - `name` and `since`: Find all packages with name `name` since `since`.
        - `since`: Find all packages since `since`.
        - `name`: Find all packages with name `name`.
    All other combinations are disallowed.

    In more formal terms, a query is valid
        iff `((name and not since) or (not version and since))`
    where a given variable name means that query parameter was passed. Equivalently, a request is invalid
        iff `(not (name or since) or (version and since))`
    """

    nn_name = name is not None
    nn_version = version is not None
    nn_since = since is not None

    if (not nn_name and not nn_since) or (nn_version and nn_since):
        raise HTTPException(status_code=400)

    query = select(Package)
    if nn_name:
        query = query.where(Package.name == name)
    if nn_version:
        query = query.where(Package.version == version)
    if nn_since:
        query = query.where(Package.finished_at >= dt.datetime.utcfromtimestamp(since))

    data = await session.scalars(query)
    return data.all()
