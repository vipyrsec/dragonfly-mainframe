from typing import Optional

import pytest
from fastapi.testclient import TestClient

from mainframe.__main__ import app

client = TestClient(app)


@pytest.mark.parametrize(
    "since,name,version",
    [
        (0xC0FFEE, "name", "ver"),
        (0, None, "ver"),
        (None, None, "ver"),
        (None, None, None),
    ],
)
def test_package_lookup_rejects_invalid_combinations(since: Optional[int], name: Optional[str], version: Optional[str]):
    """Test that invalid combinations are rejected with a 400 response code."""

    since_q = name_q = version_q = ""
    if since is not None:
        since_q = f"since={since}"
    if name is not None:
        name_q = f"name={name}"
    if version is not None:
        version_q = f"version={version}"

    print(f"/package?{since_q}&{name_q}&{version_q}")
    r = client.get(f"/package?{since_q}&{name_q}&{version_q}")

    assert r.status_code == 400
