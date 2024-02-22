import logging
from datetime import datetime, timedelta
from typing import Generator
from unittest.mock import MagicMock

import pytest
import requests
from letsbuilda.pypi import PyPIServices
from letsbuilda.pypi.models import Package as PyPIPackage
from letsbuilda.pypi.models.models_package import Distribution, Release
from msgraph.core import GraphClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from mainframe.constants import mainframe_settings
from mainframe.json_web_token import AuthenticationData
from mainframe.models.orm import Base, Package
from mainframe.rules import Rules

from .test_data import data

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__file__)


@pytest.fixture(scope="session")
def sm(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, join_transaction_mode="create_savepoint", expire_on_commit=False)


@pytest.fixture(scope="session")
def engine() -> Engine:
    return create_engine(mainframe_settings.db_url)


@pytest.fixture(params=data, scope="session", autouse=True)
def initial_populate_db(request: pytest.FixtureRequest, engine: Engine, sm: sessionmaker[Session]):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    packages: list[Package] = request.param

    session = sm()
    session.add_all(packages)
    session.commit()


@pytest.fixture(autouse=True)
def db_session(sm: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = sm()
    session.commit = lambda: session.flush()
    yield session
    session.rollback()


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
    session = requests.Session()
    pypi_client = PyPIServices(session)

    def side_effect(name: str, version: str) -> PyPIPackage:
        return PyPIPackage(
            title=name,
            releases=[Release(version=version, distributions=[Distribution(filename="test", url="test")])],
        )

    pypi_client.get_package_metadata = MagicMock(side_effect=side_effect)
    return pypi_client


@pytest.fixture(scope="session")
def graph_client() -> GraphClient:
    return MagicMock(spec=GraphClient)  # type: ignore
