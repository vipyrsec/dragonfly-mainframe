"""Utilities related to PyPI"""

from urllib.parse import urlparse


def file_path_from_inspector_url(inspector_url: str) -> str:
    """Parse the file path out of a PyPI inspector URL"""

    s = "/"
    return s.join(urlparse(inspector_url).path.strip(s).split(s)[8:])
