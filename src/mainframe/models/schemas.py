from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Error(BaseModel):
    """Error"""

    detail: str


class PackageScanResult(BaseModel):
    """Result of scanning a package."""

    most_malicious_file: Optional[str]
    score: int


class JobResult(BaseModel):
    """Package information of a requested job."""

    package_id: UUID
    name: str
    version: str


class NoJob(BaseModel):
    """Returned when no available jobs were found."""

    detail: str
