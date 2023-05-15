import datetime as dt
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Generator

import pytest
import requests
from sqlalchemy import Engine, create_engine, insert
from sqlalchemy.orm import Session, sessionmaker

from mainframe.models.orm import Base, Package, Status

_api_url = "http://localhost:8000"

server = subprocess.Popen(["pdm", "run", "uvicorn", "src.mainframe.server:app"])

for _ in range(15):
    time.sleep(1)
    try:
        r = requests.get(f"{_api_url}/package?since=0", timeout=5)
        if r.status_code == 500:
            break
    except requests.exceptions.ConnectionError:
        continue
else:
    print("Server did not start in time")
    sys.exit(1)


TEST_DIR = Path(__file__).parent
TEST_DATA_DIR = TEST_DIR / "test_data"
TEST_DATA_FILES = list(TEST_DATA_DIR.iterdir())


@pytest.fixture(scope="session")
def engine() -> Engine:
    return create_engine("postgresql://postgres:postgres@db:5432")


@pytest.fixture(scope="session")
def sm(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=True)


@pytest.fixture
def api_url() -> str:
    return _api_url


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
            elif key == "package_id":
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
    Base.metadata.create_all(engine)
    with sm() as sess:
        sess.execute(insert(Package), test_data)
        sess.commit()
        yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(sm) -> Generator[Session, None, None]:
    with sm() as sess:
        yield sess
