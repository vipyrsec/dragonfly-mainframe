from typing import Optional

from pydantic import BaseModel


class ServerMetadata(BaseModel):
    """Server metadata"""

    server_commit: str
    rules_commit: str


class Error(BaseModel):
    """Error"""

    detail: str


class Package(BaseModel):
    """Model representing a package queried from the database."""

    scan_id: str
    name: str
    version: str = ""
    status: str = ""
    score: Optional[int] = 0  # Just for the sake of texting, remove upon merge
    inspector_url: Optional[str] = ""
    rules: list[str] = []
    download_urls: list[str] = []
    queued_at: str = ""
    queued_by: str = ""
    pending_at: Optional[str] = None
    pending_by: Optional[str] = None
    finished_at: Optional[str] = None
    finished_by: Optional[str] = None
    commit_hash: Optional[str] = ""

    @classmethod
    def build_from_db(cls, scan_result): # I'm... not sure of what type `scan_result` is. I'll ask later.
        return cls(
            scan_id=str(scan_result.scan_id),
            name=scan_result.name,
            version=scan_result.version,
            status=scan_result.status,
            score=scan_result.score,
            inspector_url=scan_result.inspector_url,
            rules=[rule.rule_name for rule in scan_result.rules],
            download_urls=[url.url for url in scan_result.download_urls],
            queued_at=scan_result.queued_at.isoformat(),
            queued_by=scan_result.queued_by,
            pending_at=scan_result.pending_at.isoformat() if scan_result.pending_at else None,
            pending_by=scan_result.pending_by,
            finished_at=scan_result.finished_at.isoformat() if scan_result.finished_at else None,
            finished_by=scan_result.finished_by,
            commit_hash=scan_result.commit_hash,
        )


class PackageSpecifier(BaseModel):
    """
    Model used to specify a package by name and version

    name:  A str of the name of the package to be scanned
    version: An optional str of the package version to scan. If omitted, latest version is used
    """

    name: str
    version: str

    class Config:
        frozen = True


class ReportPackageBody(PackageSpecifier):
    recipient: Optional[str]
    inspector_url: Optional[str]
    additional_information: Optional[str]


class PackageScanResult(PackageSpecifier):
    """Client payload to server containing the results of a package scan"""

    commit: str
    score: int = 0
    inspector_url: Optional[str] = None
    rules_matched: list[str] = []


class PackageScanResultFail(PackageSpecifier):
    """The client's reason as to why scanning a package failed"""

    reason: str


class JobResult(BaseModel):
    """Package information of a requested job."""

    name: str
    version: str
    distributions: list[str]
    hash: str


class GetRules(BaseModel):
    hash: str
    rules: dict[str, str]


class NoJob(BaseModel):
    """Returned when no available jobs were found."""

    detail: str


class QueuePackageResponse(BaseModel):
    """Returned after queueing a package. Contains the UUID"""

    id: str


class StatsResponse(BaseModel):
    """Recent system statistics"""

    ingested: int
    average_scan_time: float
    failed: int
