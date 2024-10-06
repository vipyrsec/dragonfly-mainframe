from collections.abc import Sequence, Generator
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock

import httpx
import pytest
from letsbuilda.pypi import PyPIServices
from letsbuilda.pypi.models import Package
from letsbuilda.pypi.models.models_package import Distribution, Release
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from mainframe.database import DatabaseStorage, StorageProtocol
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Base, Scan
from mainframe.rules import Rules

from .test_data import data

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__file__)

class MockDatabase(StorageProtocol):
    def __init__(self) -> None:
        self.db: list[Scan] = []

    def add(self, scan: Scan) -> None:
        self.db.append(scan)

    def lookup_packages(
        self, name: Optional[str] = None, version: Optional[str] = None, since: Optional[datetime] = None
    ) -> Sequence[Scan]:
        v: list[Scan] = []
        for scan in self.db:
            if (
                (scan.name == name)
                or (scan.version == version)
                or (scan.queued_at and since and scan.queued_at >= since)
            ):
                v.append(scan)

        return v

    def mark_reported(self, *, scan: Scan, subject: str) -> None:
        for s in self.db:
            if s.scan_id == scan.scan_id:
                scan.reported_by = subject
                scan.reported_at = datetime.now()

@pytest.fixture
def mock_database() -> MockDatabase:
    return MockDatabase()

@pytest.fixture(scope="session")
def sm(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autobegin=False)


@pytest.fixture(scope="session")
def superuser_engine() -> Engine:
    """
    Creates an engine using a user with superuser permissions.

    This should only be used for tests that need superuser permissions.
    Otherwise, tests should prefer the `engine` fixture in order to better
    mimic the production user.
    """
    return create_engine("postgresql+psycopg2://postgres:postgres@db:5432/dragonfly", pool_size=5, max_overflow=10)


@pytest.fixture(scope="session")
def engine(superuser_engine: Engine) -> Engine:
    with Session(bind=superuser_engine) as s, s.begin():
        s.execute(text("DROP USER IF EXISTS dragonfly"))
        s.execute(text("CREATE USER dragonfly WITH LOGIN PASSWORD 'postgres'"))
        s.execute(text("GRANT pg_read_all_data TO dragonfly"))
        s.execute(text("GRANT pg_write_all_data TO dragonfly"))

    return create_engine("postgresql+psycopg2://dragonfly:postgres@db:5432/dragonfly", pool_size=5, max_overflow=10)


@pytest.fixture(params=data, scope="session")
def test_data(request: pytest.FixtureRequest) -> list[Scan]:
    return request.param


@pytest.fixture
def db_session(
    superuser_engine: Engine, test_data: list[Scan], sm: sessionmaker[Session]
) -> Generator[Session, None, None]:
    Base.metadata.drop_all(superuser_engine)
    Base.metadata.create_all(superuser_engine)
    with sm() as s, s.begin():
        s.add_all(deepcopy(test_data))

    with sm() as s:
        yield s

    Base.metadata.drop_all(superuser_engine)


@pytest.fixture(scope="session")
def auth() -> AuthenticationData:
    return AuthenticationData(
        issuer="DEVELOPMENT ISSUER",
        subject="DEVELOPMENT SUBJECT",
        audience="DEVELOPMENT AUDIENCE",
        issued_at=datetime.now() - timedelta(seconds=10),
        expires_at=datetime.now() + timedelta(seconds=10),
        grant_type="DEVELOPMENT GRANT TYPE",
    )


@pytest.fixture(scope="session")
def rules_state() -> Rules:
    return Rules(
        rules_commit="test commit hash",
        rules={
            "filename1": "rule contents 1",
            "filename2": "rule contents 2",
        },
    )


@pytest.fixture(scope="session")
def pypi_client() -> PyPIServices:
    http_client = httpx.Client()
    pypi_client = PyPIServices(http_client)

    def side_effect(name: str, version: str) -> Package:
        return Package(
            title=name,
            releases=[Release(version=version, distributions=[Distribution(filename="test", url="test")])],
        )

    pypi_client.get_package_metadata = MagicMock(side_effect=side_effect)
    return pypi_client
