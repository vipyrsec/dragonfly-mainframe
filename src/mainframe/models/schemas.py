from typing import Optional

from pydantic import BaseModel


class Error(BaseModel):
    """Error"""

    detail: str


class PackageScanResult(BaseModel):
    most_malicious_file: Optional[str]
    score: int
