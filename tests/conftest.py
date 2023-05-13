import datetime as dt
import subprocess
import sys
import time

import pytest
import requests
from sqlalchemy import Engine, create_engine, insert
from sqlalchemy.orm import sessionmaker

from mainframe.models import Base, Package, Status

_api_url = "http://localhost:8000"

server = subprocess.Popen(["python", "-m", "pdm", "run", "uvicorn", "src.mainframe.server:app"], stdout=subprocess.PIPE)

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


@pytest.fixture(scope="session")
def engine():
    return create_engine("postgresql://postgres:postgres@db:5432")


@pytest.fixture(scope="session")
def sm(engine):
    return sessionmaker(bind=engine, autoflush=True)


@pytest.fixture
def api_url():
    return _api_url


@pytest.fixture
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
            status=Status.FINISHED,
            score=None,
            most_malicious_file=None,
            queued_at=dt.datetime(2023, 5, 12, 15),
            pending_at=dt.datetime(2023, 5, 12, 16),
            finished_at=dt.datetime(2023, 5, 12, 16, 30),
            client_id="remmy",
            reported_at=dt.datetime(2023, 5, 12, 16, 30, 6),
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
        dict(
            package_id="bbb953ca-95af-4d57-a7a5-0b656f652695",
            name="b",
            version="0.2.0",
            status=Status.PENDING,
            score=None,
            most_malicious_file=None,
            queued_at=dt.datetime(2023, 5, 12, 19),
            pending_at=dt.datetime(2023, 5, 12, 20),
            finished_at=None,
            client_id="remmy",
            reported_at=None,
        ),
    ]


@pytest.fixture(autouse=True)
def db_setup(engine: Engine, sm: sessionmaker, test_data: list[dict]):
    Base.metadata.create_all(engine)
    with sm() as sess:
        sess.execute(insert(Package), test_data)
        sess.commit()
        yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(sm):
    with sm() as sess:
        yield sess
