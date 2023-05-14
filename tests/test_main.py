import asyncio
import datetime as dt
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mainframe.__main__ import app
from mainframe.models.orm import Package, Status

pytest_plugins = ("pytest_asyncio",)


client = TestClient(app)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def async_session():
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@db:5432")
    asm = async_sessionmaker(bind=engine, expire_on_commit=False)

    async with asm() as session:
        await session.execute(
            insert(Package),
            [
                dict(
                    package_id="fce0366b-0bcf-4a29-a0a7-4d4bdf3c6f61",
                    name="a",
                    version="0.1.0",
                    status=Status.FINISHED,
                    queued_at=dt.datetime.now(),
                ),
                dict(
                    package_id="df157a3c-8994-467f-a494-9d63eaf96564",
                    name="b",
                    version="0.1.0",
                    status=Status.PENDING,
                    queued_at=dt.datetime.now(),
                ),
                dict(
                    package_id="04685768-e41d-49e4-9192-19b6d435226a",
                    name="a",
                    version="0.2.0",
                    status=Status.QUEUED,
                    queued_at=dt.datetime.now(),
                ),
            ],
        )
        await session.commit()

    yield asm


@pytest.fixture
async def session(async_session):
    session = async_session()
    yield session
    await session.close()


@pytest.mark.parametrize(
    "since,name,version",
    [
        (0xC0FFEE, "name", "ver"),
        (0, None, "ver"),
        (None, None, "ver"),
        (None, None, None),
    ],
)
def test_package_lookup_rejects_invalid_combinations(since: Optional[int], name: Optional[str], version: Optional[str]):
    """Test that invalid combinations are rejected with a 400 response code."""

    since_q = name_q = version_q = ""
    if since is not None:
        since_q = f"since={since}"
    if name is not None:
        name_q = f"name={name}"
    if version is not None:
        version_q = f"version={version}"

    url = f"/package?{since_q}&{name_q}&{version_q}"
    print(url)
    r = client.get(url)

    assert r.status_code == 400


async def test_package_lookup(session: AsyncSession):
    print(session)

    assert False
