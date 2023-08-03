from typing import Optional

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from mainframe.models.orm import Scan


def build_query_string(since: Optional[int], name: Optional[str], version: Optional[str]) -> str:
    """Helper function for generating query parameters."""
    since_q = name_q = version_q = ""
    if since is not None:
        since_q = f"since={since}"
    if name is not None:
        name_q = f"name={name}"
    if version is not None:
        version_q = f"version={version}"

    params = [since_q, name_q, version_q]

    url = f"/package?{'&'.join(x for x in params if x != '')}"
    return url


@pytest.mark.parametrize(
    "inp,exp",
    [
        ((0, "name", "ver"), "/package?since=0&name=name&version=ver"),
        ((0, None, "ver"), "/package?since=0&version=ver"),
        ((None, None, "ver"), "/package?version=ver"),
        ((None, None, None), "/package?"),
    ],
)
def test_build_query_string(inp: tuple[Optional[int], Optional[str], Optional[str]], exp: str):
    """Test build_query_string"""
    out = build_query_string(*inp)
    print(out)
    assert out == exp


@pytest.mark.parametrize(
    "since,name,version",
    [
        (0xC0FFEE, "name", "ver"),
        (0, None, "ver"),
        (None, None, "ver"),
        (None, None, None),
    ],
)
def test_package_lookup_rejects_invalid_combinations(
    client: TestClient,
    since: Optional[int],
    name: Optional[str],
    version: Optional[str],
):
    """Test that invalid combinations are rejected with a 400 response code."""

    url = build_query_string(since, name, version)
    print(url)

    r = client.get(url)
    assert r.status_code == 400


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
    client: TestClient,
    since: Optional[int],
    name: Optional[str],
    version: Optional[str],
    test_data: list[dict],
):
    url = build_query_string(since, name, version)
    print(url)
    exp = []
    for d in test_data:
        if since is not None and (d["finished_at"] is None or since > int(d["finished_at"].timestamp())):
            continue
        if name is not None and d["name"] != name:
            continue
        if version is not None and d["version"] != version:
            continue
        exp.append(d)

    r = client.get(url)
    print(repr(r.text))

    def key(d):
        return d["scan_id"]

    assert sorted(r.json(), key=key) == sorted(jsonable_encoder(exp), key=key)


def test_batch_queue(client: TestClient, db_session: Session, test_data: list[dict]):
    data = [dict(name=t["name"], version=t["version"]) for t in test_data] + [dict(name="c", version="1.0.0")]
    print(data)
    r = client.post("/batch/package", json=data)
    r.raise_for_status()

    for row in db_session.scalars(select(Scan)):
        assert dict(name=row.name, version=row.version) in data
