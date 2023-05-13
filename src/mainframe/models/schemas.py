from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Error:
    """Error"""

    detail: str


@dataclass(frozen=True)
class PackageScanResult:
    most_malicious_file: Optional[str]
    score: int
