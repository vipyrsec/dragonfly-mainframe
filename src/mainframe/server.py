import datetime as dt
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Package

load_dotenv()

engine = create_async_engine(os.getenv("DB_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432"))
async_session = async_sessionmaker(bind=engine, expire_on_commit=False)
app = FastAPI()


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
