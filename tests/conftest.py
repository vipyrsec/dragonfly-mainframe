import datetime as dt

import pytest

from mainframe.models import Status

pytest_plugins = ("pytest_asyncio",)


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
