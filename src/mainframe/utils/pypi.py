"""Utilities related to PyPI."""

from urllib.parse import urlparse


def file_path_from_inspector_url(inspector_url: str) -> str:
    """Parse the file path out of a PyPI inspector URL."""
    parsed_url = urlparse(inspector_url)
    path = parsed_url.path.strip("/")
    segments = path.split("/")

    # The 8th element of path is when the file path starts
    return "/".join(segments[8:])
