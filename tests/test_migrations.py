from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text

from alembic import command

from .conftest import DB_URL

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def db_session():
    """Override conftest's autouse ``db_session`` fixture.

    This test manages its own throwaway database and must not have the
    ``Base.metadata`` tables pre-created (nor be multiplied across the
    ``test_data`` params that the conftest fixture pulls in).
    """
    return


@pytest.fixture
def migration_db_url():
    """Create a throwaway database for the migration run, drop it afterwards."""
    db_name = "dragonfly_migration_test"
    admin_url = make_url(DB_URL).set(username="postgres", database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        yield str(make_url(DB_URL).set(username="postgres", database=db_name))
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def _alembic_config() -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return cfg


def test_migrations_round_trip(migration_db_url: str, monkeypatch: pytest.MonkeyPatch):
    """Upgrade to head and back to base twice against a clean database.

    ``alembic/env.py`` reads the database URL from the ``DB_URL`` environment
    variable, so point it at the throwaway database. Any failing migration
    raises and fails the test. The second ``upgrade``/``downgrade`` pass guards
    against migrations that leave objects behind on downgrade (e.g. the
    ``status`` ENUM type or a stale ``rules_pkey`` constraint).
    """
    monkeypatch.setenv("DB_URL", migration_db_url)
    cfg = _alembic_config()

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
