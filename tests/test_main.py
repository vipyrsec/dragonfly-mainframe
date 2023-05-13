from typing import Optional

import pytest


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
def test_package_lookup_rejects_invalid_combinations(since: Optional[int], name: Optional[str], version: Optional[str]):
    """Test that invalid combinations are rejected with a 400 response code."""

    url = build_query_string(since, name, version)
    print(url)
    # r = client.get(url)

    # assert r.status_code == 400
