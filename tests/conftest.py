import datetime as dt
import json
import logging
import uuid
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, insert
from sqlalchemy.orm import Session, sessionmaker

from mainframe.models.orm import Base, Scan, Status
from mainframe.server import app

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__file__)


_api_url = "http://localhost:8000"

TEST_DIR = Path(__file__).parent
TEST_DATA_DIR = TEST_DIR / "test_data"
TEST_DATA_FILES = list(TEST_DATA_DIR.iterdir())
# TEST_DATA_FILES = [TEST_DATA_DIR / "sample.json"]


@pytest.fixture(scope="session")
def engine() -> Engine:
    return create_engine("postgresql+psycopg2://postgres:postgres@db:5432")


@pytest.fixture(scope="session")
def sm(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=True)


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app, base_url=_api_url) as client:
        yield client


def decode(L) -> list[dict]:
    out = []
    for d in L:
        new_d = d.copy()
        for key, value in d.items():
            if key == "status":
                new_d[key] = Status(value)
            elif key in ["queued_at", "pending_at", "finished_at", "reported_at"]:
                if value is not None:
                    new_d[key] = dt.datetime.fromisoformat(value)
            elif key == "scan_id":
                new_d[key] = uuid.UUID(f"{{{value}}}")

        out.append(new_d)

    return out


@pytest.fixture(params=TEST_DATA_FILES, ids=[p.name for p in TEST_DATA_FILES])
def test_data(request) -> list[dict]:
    with open(request.param) as f:
        data = json.load(f)

    return decode(data)


@pytest.fixture(autouse=True)
def db_setup(engine: Engine, sm: sessionmaker, test_data: list[dict]) -> Generator[None, None, None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with sm() as sess:
        sess.execute(insert(Scan), test_data)
        sess.commit()
        yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(sm) -> Generator[Session, None, None]:
    with sm() as sess:
        yield sess
