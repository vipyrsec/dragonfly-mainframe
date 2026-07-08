from http import HTTPStatus
from unittest.mock import MagicMock

import httpx
import pytest

from mainframe.pypi import PackageNotFoundError, PyPIClient

SAMPLE_RESPONSE = {
    "info": {"name": "requests", "version": "2.32.3"},
    "urls": [
        {"url": "https://files.pythonhosted.org/requests-2.32.3.tar.gz", "filename": "requests-2.32.3.tar.gz"},
        {"url": "https://files.pythonhosted.org/requests-2.32.3-py3-none-any.whl"},
    ],
}


def _make_mock_http_client(response: httpx.Response) -> MagicMock:
    response.request = httpx.Request("GET", "https://pypi.org/pypi/test/json")
    http_client = MagicMock(spec=httpx.Client)
    http_client.get.return_value = response
    return http_client


def test_get_package_metadata_with_version():
    http_client = _make_mock_http_client(httpx.Response(HTTPStatus.OK, json=SAMPLE_RESPONSE))

    metadata = PyPIClient(http_client).get_package_metadata("requests", "2.32.3")

    http_client.get.assert_called_once_with("https://pypi.org/pypi/requests/2.32.3/json")
    assert metadata.name == "requests"
    assert metadata.version == "2.32.3"
    assert [d.url for d in metadata.distributions] == [
        "https://files.pythonhosted.org/requests-2.32.3.tar.gz",
        "https://files.pythonhosted.org/requests-2.32.3-py3-none-any.whl",
    ]


def test_get_package_metadata_ignores_unmodelled_and_missing_fields():
    """Extra fields are ignored and a release with no distributions is tolerated."""
    payload = {"info": {"name": "empty", "version": "1.0.0", "yanked": None}, "extra": "ignored"}
    http_client = _make_mock_http_client(httpx.Response(HTTPStatus.OK, json=payload))

    metadata = PyPIClient(http_client).get_package_metadata("empty", "1.0.0")

    assert metadata.distributions == []


def test_get_package_metadata_ignores_extra_pypi_fields():
    """Regression: unknown fields PyPI may add must be ignored, not crash parsing.

    The real PyPI JSON response carries many more keys than we model, at the
    top level and nested inside ``info`` and each ``urls`` entry. This mirrors
    a realistic response (the fields we use plus a representative sample of
    extras) and confirms the extras are silently dropped while the fields we
    care about still parse correctly.
    """
    payload = {
        "info": {
            "name": "requests",
            "version": "2.32.3",
            # Fields PyPI returns that we deliberately don't model.
            "author": "Kenneth Reitz",
            "summary": "Python HTTP for Humans.",
            "requires_python": ">=3.8",
            "yanked": False,
            "classifiers": ["Programming Language :: Python :: 3"],
            "project_urls": {"Homepage": "https://requests.readthedocs.io"},
        },
        "urls": [
            {
                "url": "https://files.pythonhosted.org/requests-2.32.3.tar.gz",
                # Extra per-distribution fields we don't model.
                "filename": "requests-2.32.3.tar.gz",
                "packagetype": "sdist",
                "size": 131218,
                "yanked": False,
                "digests": {"sha256": "deadbeef"},
                "upload_time_iso_8601": "2024-05-29T15:37:49.000000Z",
            },
        ],
        # A brand-new top-level key PyPI might add in the future.
        "vulnerabilities": [],
        "some_future_field": {"nested": "value"},
    }
    http_client = _make_mock_http_client(httpx.Response(HTTPStatus.OK, json=payload))

    metadata = PyPIClient(http_client).get_package_metadata("requests", "2.32.3")

    # The fields we care about parse correctly...
    assert metadata.name == "requests"
    assert metadata.version == "2.32.3"
    assert [d.url for d in metadata.distributions] == ["https://files.pythonhosted.org/requests-2.32.3.tar.gz"]
    # ...and none of the unmodelled extras leak onto our models.
    assert "size" not in metadata.distributions[0].model_dump()
    assert set(metadata.model_dump()) == {"name", "version", "distributions"}


def test_get_package_metadata_not_found():
    http_client = _make_mock_http_client(httpx.Response(HTTPStatus.NOT_FOUND))

    with pytest.raises(PackageNotFoundError) as exc_info:
        PyPIClient(http_client).get_package_metadata("does-not-exist", "9.9.9")

    assert exc_info.value.name == "does-not-exist"
    assert exc_info.value.version == "9.9.9"
