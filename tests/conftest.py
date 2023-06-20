import datetime as dt
import json
import logging
import subprocess
import time
import uuid
from pathlib import Path
from typing import IO, Generator, cast

import conc_read
import pytest
from sqlalchemy import Engine, create_engine, insert
from sqlalchemy.orm import Session, sessionmaker

from mainframe.models.orm import Base, Scans, Status

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__file__)

_api_url = "http://localhost:8000"


TEST_DIR = Path(__file__).parent
TEST_DATA_DIR = TEST_DIR / "test_data"
TEST_DATA_FILES = list(TEST_DATA_DIR.iterdir())
# TEST_DATA_FILES = [TEST_DATA_DIR / "sample.json"]


logger.info("Starting server subprocess")

if logger.isEnabledFor(logging.INFO):
    start_point = time.perf_counter()

server = subprocess.Popen(
    ["pdm", "run", "uvicorn", "src.mainframe.server:app"], stderr=subprocess.PIPE, universal_newlines=True, bufsize=1
)
concurrent_reader = conc_read.ConcurrentReader(cast(IO, server.stderr), poll_freq=20)


def pytest_sessionstart():
    # This startup section is slightly cursed, but works relatively well. The
    # idea is that we start the server as a subprocess in order to make http
    # requests to it. However, we need to wait for some time in order to make
    # sure that the server is ready to handle our requests.

    # So to do that, we simply read the server logs until we find "Application
    # startup complete".

    for line in concurrent_reader:
        if line is None:
            time.sleep(0.1)
            continue
        if "Uvicorn running on" in line:
            break

    logger.info(f"Server started in {time.perf_counter() - start_point}s")


def pytest_sessionfinish():
    concurrent_reader.close()


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
        sess.execute(insert(Scans), test_data)
        sess.commit()
        yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(sm) -> Generator[Session, None, None]:
    with sm() as sess:
        yield sess
