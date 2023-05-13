from operator import itemgetter
from typing import Optional

import pytest
import requests
from fastapi.encoders import jsonable_encoder


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
    since: Optional[int], name: Optional[str], version: Optional[str], api_url: str
):
    """Test that invalid combinations are rejected with a 400 response code."""

    url = build_query_string(since, name, version)
    print(url)

    r = requests.get(api_url + url)
    assert r.status_code == 400


@pytest.mark.parametrize(
    "since,name,version,exp",
    [
        (0, "a", None, [0]),
        (0, None, None, [0, 1]),
        (0, "b", None, [1]),
    ],
)
def test_package_lookup(
    since: Optional[int], name: Optional[str], version: Optional[str], exp: list[int], api_url: str, test_data
):
    url = build_query_string(since, name, version)
    print(url)

    ans = itemgetter(*exp)(test_data)
    if len(exp) == 1:
        ans = [ans]

    r = requests.get(api_url + url)
    print(repr(r.text))

    def key(d):
        return d["package_id"]

    assert sorted(r.json(), key=key) == sorted(jsonable_encoder(ans), key=key)
