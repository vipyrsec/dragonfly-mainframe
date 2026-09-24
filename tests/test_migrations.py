import pytest
from pytest_alembic.tests import (
    test_single_head_revision,
    test_upgrade,
    test_up_down_consistency,
)

@pytest.fixture(autouse=False)
def db_session():
    return
