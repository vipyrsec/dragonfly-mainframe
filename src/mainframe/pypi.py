"""A minimal in-house client for the PyPI JSON API.

This replaces the third-party ``letsbuilda-pypi`` dependency. Only the handful
of fields that mainframe actually consumes are modelled here; every other field
in the PyPI response is ignored. Keeping the surface this small insulates us
from the many under-documented quirks of the upstream API (fields that are
nullable in practice but not in the docs, enum types with undocumented values,
etc.) — if PyPI adds or changes a field we don't read, we simply don't care.
"""

from http import HTTPStatus
from typing import Self

import httpx
from pydantic import BaseModel, Field

PYPI_BASE_URL = "https://pypi.org/pypi"


class PackageNotFoundError(Exception):
    """Raised when a package (or a specific version of it) is not found on PyPI."""

    def __init__(self: Self, name: str, version: str | None = None) -> None:
        self.name = name
        self.version = version
        super().__init__(f"'{name}' @ '{version}' not found on PyPI!")


class Distribution(BaseModel):
    """A single downloadable file (e.g. an sdist or wheel) for a release."""

    url: str


class PackageMetadata(BaseModel):
    """The subset of PyPI package metadata that mainframe uses."""

    name: str
    version: str
    distributions: list[Distribution]


class _Info(BaseModel):
    """The `info` object of the PyPI JSON response (only the fields we read)."""

    name: str
    version: str


class _JSONResponse(BaseModel):
    """The shape of the PyPI JSON response, limited to what we parse."""

    info: _Info
    urls: list[Distribution] = Field(default_factory=list[Distribution])


class PyPIClient:
    """A minimal synchronous client for the PyPI JSON API."""

    def __init__(self: Self, http_client: httpx.Client) -> None:
        self.http_client = http_client

    def get_package_metadata(self: Self, name: str, version: str | None = None) -> PackageMetadata:
        """Fetch metadata for a package, optionally pinned to a specific version.

        Args:
            name: The package name.
            version: The package version. If omitted, the latest release is used.

        Returns:
            The metadata for the requested package.

        Raises:
            PackageNotFoundError: If the package or version does not exist on PyPI.
        """
        url = f"{PYPI_BASE_URL}/{name}/{version}/json" if version is not None else f"{PYPI_BASE_URL}/{name}/json"

        response = self.http_client.get(url)
        if response.status_code == HTTPStatus.NOT_FOUND:
            raise PackageNotFoundError(name, version)
        response.raise_for_status()

        data = _JSONResponse.model_validate(response.json())
        return PackageMetadata(
            name=data.info.name,
            version=data.info.version,
            distributions=data.urls,
        )
