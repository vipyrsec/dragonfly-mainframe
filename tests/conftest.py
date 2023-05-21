import datetime as dt
import json
import logging
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import IO, Generator, cast

import conc_read
import pytest
from sqlalchemy import Engine, create_engine, insert
from sqlalchemy.orm import Session, sessionmaker

from mainframe.models.orm import Base, Package, Status

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__file__)

TIMEOUT = 30

_api_url = "http://localhost:8000"

# This startup section is slightly cursed, but works relatively well. The idea
# is that we start the server as a subprocess in order to make http requests to
# it. However, we need to wait for some time in order to make sure that the
# server is ready to handle our requests.
#
# So to do that, we simply read the server logs until we find "Application
# startup complete" Afterwards, we restore the stderr of the subprocess to
# `sys.stderr` to be able to see any further logs that pop up

logger.info("Starting server subprocess")
server = subprocess.Popen(
    ["pdm", "run", "uvicorn", "src.mainframe.server:app"], stderr=subprocess.PIPE, universal_newlines=True
)

r = conc_read.ConcurrentReader(cast(IO, server.stderr))

with r:
    for x in r:
        if x is None:
            continue
        logging.debug(x)
        if "Application startup complete" in x:
            break
        time.sleep(0.2)

server.stderr = sys.stderr


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
