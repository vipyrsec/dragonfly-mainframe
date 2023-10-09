from typing import Optional

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from mainframe.endpoints.package import lookup_package_info
from mainframe.models.orm import Scan


@pytest.mark.parametrize(
    "name,version,since",
    [
        ("a", None, 0),
        (None, None, 0),
        ("b", None, 0),
        ("a", "0.1.0", None),
    ],
)
def test_package_lookup(
    name: Optional[str],
    version: Optional[str],
    since: Optional[int],
    test_data: list[Scan],
    db_session: Session,
):
    exp: set[tuple[str, str]] = set()
    for scan in test_data:
        if since is not None and since > int(scan.finished_at.timestamp()):  # pyright: ignore
            continue
        if name is not None and scan.name != name:
            continue
        if version is not None and scan.version != version:
            continue
        exp.add((scan.name, scan.version))

    scans = lookup_package_info(db_session, name, version, since)
    assert exp == {(scan.name, scan.version) for scan in scans}


@pytest.mark.parametrize(
    "name,version,since",
    [
        ("name", "ver", 0xC0FFEE),
        (None, "ver", 0),
        (None, "ver", None),
        (None, None, None),
    ],
)
def test_package_lookup_rejects_invalid_combinations(
    db_session: Session,
    name: Optional[str],
    version: Optional[str],
    since: Optional[int],
):
    """Test that invalid combinations are rejected with a 400 response code."""

    with pytest.raises(HTTPException) as e:
        lookup_package_info(db_session, name, version, since)
    assert e.value.status_code == 400
