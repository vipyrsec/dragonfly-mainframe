import subprocess
import requests
import time
import sys
import datetime as dt

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import sessionmaker
from mainframe.models import Base, Status, Package

_api_url = "http://localhost:8000"

server = subprocess.Popen(["python", "-m", "pdm", "run", "uvicorn", "src.mainframe.server:app"], stdout=subprocess.PIPE)

for _ in range(5):
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
    return sessionmaker(bind=engine)


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


@pytest.fixture
def db_session(engine, sm, test_data):
    Base.metadata.create_all(engine)
    with sm() as session:
        trans = session.begin()
        session.execute(insert(Package), test_data)
        yield session
        trans.rollback()
        session.close()
    Base.metadata.drop_all(engine)
