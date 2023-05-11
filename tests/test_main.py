import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mainframe.__main__ import app

pytest_plugins = ("pytest_asyncio",)

client = TestClient(app)


@pytest.fixture(scope="module")
def async_session():
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@db:5432")
    async_session = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield async_session


@pytest.fixture
async def session(async_session):
    session = async_session()
    yield session
    await session.close()
