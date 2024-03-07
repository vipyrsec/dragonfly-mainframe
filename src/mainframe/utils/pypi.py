"""Utilities related to PyPI"""

from urllib.parse import urlparse
from letsbuilda.pypi import Package, PackageNotFoundError, PyPIServices
from typing import Optional


def file_path_from_inspector_url(inspector_url: str) -> str:
    """Parse the file path out of a PyPI inspector URL"""

    parsed_url = urlparse(inspector_url)
    path = parsed_url.path.strip("/")
    segments = path.split("/")

    # The 8th element of path is when the file path starts
    return "/".join(segments[8:])

def lookup_package(name: str, version: str, pypi_client: PyPIServices) -> Optional[Package]:
    """
    Lookup package metadata on PyPI.

    Returns:
        Package metadata from PyPI if it exists, otherwise None.
    """

    try:
        return pypi_client.get_package_metadata(name, version)
    except PackageNotFoundError:
        return None
