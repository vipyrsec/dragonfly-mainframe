from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class Error(BaseModel):
    """Error"""

    detail: str


class PackageScanResult(BaseModel):
    most_malicious_file: Optional[str]
    score: int


class JobResult(BaseModel):
    package_id: UUID


class NoJob(BaseModel):
    detail: str
