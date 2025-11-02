import datetime
from enum import Enum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from .orm import Scan


class ServerMetadata(BaseModel):
    """Server metadata."""

    server_commit: str
    rules_commit: str


class Error(BaseModel):
    """Error."""

    detail: str


class Package(BaseModel):
    """Model representing a package queried from the database."""

    scan_id: str
    name: str
    version: str | None
    status: str | None
    score: int | None
    inspector_url: str | None
    rules: list[str] = []
    download_urls: list[str] = []
    queued_at: datetime.datetime | None
    queued_by: str | None
    reported_at: datetime.datetime | None
    reported_by: str | None

    pending_at: datetime.datetime | None

    pending_by: str | None
    finished_at: datetime.datetime | None
    finished_by: str | None

    commit_hash: str | None

    @classmethod
    def from_db(cls, scan: Scan) -> Self:
        return cls(
            scan_id=str(scan.scan_id),
            name=scan.name,
            version=scan.version,
            status=scan.status.name.lower(),
            score=scan.score,
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
    def serialize_dt(self, dt: datetime.datetime | None) -> int | None:
        if dt:
            return int(dt.timestamp())
        return None  # pragma: no cover


class PackageSpecifier(BaseModel):
    """Model used to specify a package by name and version.

    name:  A str of the name of the package to be scanned
    version: A str of the package version to scan.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    version: str


class ReportPackageBody(PackageSpecifier):
    inspector_url: str | None
    additional_information: str


# Taken from
# https://github.com/pypi/warehouse/blob/4d2628560e6e764dc80a026fa080e9cf70446c81/warehouse/observations/models.py#L109-L122
class ObservationKind(Enum):
    DependencyConfusion = "is_dependency_confusion"
    Malware = "is_malware"
    Spam = "is_spam"
    Other = "something_else"


class ObservationReport(BaseModel):
    """Model for a report using the PyPI Observation API."""

    kind: ObservationKind
    summary: str
    inspector_url: str | None
    extra: dict[str, Any] = Field(default_factory=dict)


class PackageScanResult(PackageSpecifier):
    """Client payload to server containing the results of a package scan."""

    commit: str
    score: int = 0
    inspector_url: str | None = None
    rules_matched: list[str] = []


class PackageScanResultFail(PackageSpecifier):
    """The client's reason as to why scanning a package failed."""

    reason: str


class SuppressedPackageResponse(BaseModel):
    name: str
    version: str
    scan_id: str
    suppressed_at: Optional[str] = None
    rules: list[str] = []


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
    """Returned after queueing a package. Contains the UUID."""

    id: str


class StatsResponse(BaseModel):
    """Recent system statistics."""

    ingested: int
    average_scan_time: float
    failed: int
