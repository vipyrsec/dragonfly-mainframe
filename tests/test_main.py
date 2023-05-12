import asyncio
import datetime as dt
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mainframe.__main__ import app
from mainframe.models import Package, Status

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(scope="session")
def test_data():
    return [
        dict(
            package_id="fce0366b-0bcf-4a29-a0a7-4d4bdf3c6f61",
            name="a",
            version="0.1.0",
            status=Status.FINISHED,
            score=0,
            most_malicious_file="main.py",
            queued_at=dt.datetime(2023, 5, 12, 18),
            pending_at=dt.datetime(2023, 5, 12, 18, 30),
            finished_at=dt.datetime(2023, 5, 12, 19),
            client_id="remmy",
            reported_at=None,
        ),
        dict(
            package_id="df157a3c-8994-467f-a494-9d63eaf96564",
            name="b",
            version="0.1.0",
            status=Status.PENDING,
            score=None,
            most_malicious_file=None,
            queued_at=dt.datetime(2023, 5, 12, 15),
            pending_at=dt.datetime(2023, 5, 12, 16),
            finished_at=None,
            client_id="remmy",
            reported_at=None,
        ),
        dict(
            package_id="04685768-e41d-49e4-9192-19b6d435226a",
            name="a",
            version="0.2.0",
            status=Status.QUEUED,
            score=None,
            most_malicious_file=None,
            queued_at=dt.datetime(2023, 5, 12, 17),
            pending_at=None,
            finished_at=None,
            client_id=None,
            reported_at=None,
        ),
    ]


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def async_session():
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@db:5432")
    asm = async_sessionmaker(bind=engine, expire_on_commit=False)

    return asm


@pytest.fixture
async def session(async_session):
    session = async_session()
    yield session
    await session.close()


@pytest.fixture(scope="session")
async def client(async_session, test_data):
    async with async_session() as session:
        await session.execute(insert(Package), test_data)
        await session.commit()

    return TestClient(app)


def build_query_string(since: Optional[int], name: Optional[str], version: Optional[str]) -> str:
    """Helper function for generating query parameters."""
    since_q = name_q = version_q = ""
    if since is not None:
        since_q = f"since={since}"
    if name is not None:
        name_q = f"name={name}"
    if version is not None:
        version_q = f"version={version}"

    params = [since_q, name_q, version_q]

    url = f"/package?{'&'.join(x for x in params if x != '')}"
    return url


@pytest.mark.parametrize(
    "inp,exp",
    [
        ((0, "name", "ver"), "/package?since=0&name=name&version=ver"),
        ((0, None, "ver"), "/package?since=0&version=ver"),
        ((None, None, "ver"), "/package?version=ver"),
        ((None, None, None), "/package?"),
    ],
)
def test_build_query_string(inp: tuple[Optional[int], Optional[str], Optional[str]], exp: str):
    """Test build_query_string"""
    out = build_query_string(*inp)
    print(out)
    assert out == exp


@pytest.mark.parametrize(
    "since,name,version",
    [
        (0xC0FFEE, "name", "ver"),
        (0, None, "ver"),
        (None, None, "ver"),
        (None, None, None),
    ],
)
def test_package_lookup_rejects_invalid_combinations(
    since: Optional[int], name: Optional[str], version: Optional[str], client
):
    """Test that invalid combinations are rejected with a 400 response code."""

    url = build_query_string(since, name, version)
    print(url)
    r = client.get(url)

    assert r.status_code == 400
