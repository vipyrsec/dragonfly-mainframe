from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_serializer

from mainframe.models.orm import Scan


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
    version: Optional[str]
    status: Optional[str]
    score: Optional[int]
    inspector_url: Optional[str]
    rules: list[str] = []
    download_urls: list[str] = []
    queued_at: Optional[datetime]
    queued_by: Optional[str]
    reported_at: Optional[datetime]
    reported_by: Optional[str]
    pending_at: Optional[datetime]
    pending_by: Optional[str]
    finished_at: Optional[datetime]
    finished_by: Optional[str]
    commit_hash: Optional[str]

    @classmethod
    def from_db(cls, scan: Scan):
        return cls(
            scan_id=str(scan.scan_id),
            name=scan.name,
            version=scan.version,
            status=str(scan.status),
            score=scan.score,  # pyright: ignore
            inspector_url=scan.inspector_url,
            rules=[rule.name for rule in scan.rules],
            download_urls=[url.url for url in scan.download_urls],
            reported_at=scan.reported_at,
            reported_by=scan.reported_by,
            queued_at=scan.queued_at,
            queued_by=scan.queued_by,
            pending_at=scan.pending_at,
            pending_by=scan.pending_by,
            finished_at=scan.finished_at,
            finished_by=scan.finished_by,
            commit_hash=scan.commit_hash,
        )

    @field_serializer(
        "queued_at",
        "pending_at",
        "finished_at",
        "reported_at",
    )
    def serialize_dt(self, dt: Optional[datetime], _info):  # pyright: ignore
        if dt:
            return int(dt.timestamp())


class PackageSpecifier(BaseModel):
    """
    Model used to specify a package by name and version

    name:  A str of the name of the package to be scanned
    version: A str of the package version to scan.
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
