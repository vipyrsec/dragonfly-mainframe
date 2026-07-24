"""Minimal client over PyPI JSON API."""

from http import HTTPStatus
from typing import Self

import httpx
from pydantic import BaseModel, Field

PYPI_BASE_URL = "https://pypi.org/pypi"


class PackageNotFoundError(Exception):
    """Raised when a package version is not found on PyPI."""

    def __init__(self: Self, name: str, version: str) -> None:
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


class Info(BaseModel):
    """The `info` object of the PyPI JSON response (only the fields we read)."""

    name: str
    version: str


class JSONResponse(BaseModel):
    """The shape of the PyPI JSON response, limited to what we parse."""

    info: Info
    urls: list[Distribution] = Field(default_factory=list[Distribution])


class PyPIClient:
    """A minimal synchronous client for the PyPI JSON API."""

    def __init__(self: Self, http_client: httpx.Client) -> None:
        self.http_client = http_client

    def get_package_metadata(self: Self, name: str, version: str) -> PackageMetadata:
        """Fetch metadata for a specific version of a package.

        Args:
            name: The package name.
            version: The package version.

        Returns:
            The metadata for the requested package.

        Raises:
            PackageNotFoundError: If the package or version does not exist on PyPI.
        """
        url = f"{PYPI_BASE_URL}/{name}/{version}/json"

        response = self.http_client.get(url)
        if response.status_code == HTTPStatus.NOT_FOUND:
            raise PackageNotFoundError(name, version)
        response.raise_for_status()

        data = JSONResponse.model_validate(response.json())
        return PackageMetadata(
            name=data.info.name,
            version=data.info.version,
            distributions=data.urls,
        )
