from typing import Optional

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from mainframe.endpoints.package import lookup_package_info
from mainframe.models.orm import Scan


@pytest.mark.parametrize(
    "since,name,version",
    [
        (0, "a", None),
        (0, None, None),
        (0, "b", None),
        (None, "a", "0.1.0"),
    ],
)
def test_package_lookup(
    since: Optional[int],
    name: Optional[str],
    version: Optional[str],
    test_data: list[Scan],
    db_session: Session,
):
    exp: set[tuple[str, str]] = set()
    for scan in test_data:
        if since is not None and (scan.finished_at is None or since > int(scan.finished_at.timestamp())):
            continue
        if name is not None and scan.name != name:
            continue
        if version is not None and scan.version != version:
            continue
        exp.add((scan.name, scan.version))

    scans = lookup_package_info(db_session, name, version)
    assert exp == {(scan.name, scan.version) for scan in scans}


def test_package_lookup_rejects_invalid_combinations(
    db_session: Session,
    name: Optional[str],
    version: Optional[str],
):
    """Test that invalid combinations are rejected with a 400 response code."""

    with pytest.raises(HTTPException) as e:
        lookup_package_info(db_session, name, version)
    assert e.value.status_code == 400
