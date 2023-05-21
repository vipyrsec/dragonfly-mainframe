from typing import Optional

from pydantic import BaseModel


class Error(BaseModel):
    """Error"""

    detail: str


class PackageSpecifier(BaseModel):
    """
    Model used to specify a package by name and version

    name:  A str of the name of the package to be scanned
    version: An optional str of the package version to scan. If omitted, latest version is used
    """

    name: str
    version: Optional[str]


class PackageScanResult(BaseModel):
    """Result of scanning a package."""

    most_malicious_file: Optional[str]
    score: int


class JobResult(BaseModel):
    """Package information of a requested job."""

    name: str
    version: str
    distributions: list[str]


class NoJob(BaseModel):
    """Returned when no available jobs were found."""

    detail: str


class QueuePackageResponse(BaseModel):
    """Returned after queueing a package. Contains the UUID"""

    id: str
