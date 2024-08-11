from __future__ import annotations

import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, Optional

from pydantic import BaseModel, Field, field_serializer, ConfigDict, RootModel

if TYPE_CHECKING:
    from mainframe.models.orm import Scan

type MetaValue = int | float | bool | str | bytes


class Range(BaseModel):
    """Represents the inclusive range in the source file that was matched."""

    start: int
    end: int


class Match(BaseModel):
    """Represents a specific match by a pattern in a rule."""

    range: Range
    data: list[Annotated[int, Field(ge=0, lt=256)]]


class PatternMatch(BaseModel):
    """Represents the data matched by a pattern inside a rule."""

    identifier: str
    matches: list[Match]


class RuleMatch(BaseModel):
    """Represents the matches of a rule on a file"""

    identifier: str
    patterns: list[PatternMatch]
    metadata: dict[str, MetaValue]


class File(BaseModel):
    """Represents a file and the rule matches for it."""

    path: str
    matches: list[RuleMatch]


Files = list[File]


class Distribution(BaseModel):
    download_url: str
    files: Files


Distributions = RootModel[list[Distribution]]


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
    queued_at: Optional[datetime.datetime]
    queued_by: Optional[str]
    reported_at: Optional[datetime.datetime]
    reported_by: Optional[str]

    pending_at: Optional[datetime.datetime]

    pending_by: Optional[str]
    finished_at: Optional[datetime.datetime]
    finished_by: Optional[str]

    commit_hash: Optional[str]

    distributions: Optional[Distributions]

    @classmethod
    def from_db(cls, scan: Scan):
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
            distributions=scan.distributions,
        )

    @field_serializer(
        "queued_at",
        "pending_at",
        "finished_at",
        "reported_at",
    )
    def serialize_dt(self, dt: Optional[datetime.datetime], _info):  # pyright: ignore
        if dt:
            return int(dt.timestamp())


class PackageSpecifier(BaseModel):
    """
    Model used to specify a package by name and version

    name:  A str of the name of the package to be scanned
    version: A str of the package version to scan.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    version: str


class ReportPackageBody(PackageSpecifier):
    recipient: Optional[str]
    inspector_url: Optional[str]
    additional_information: Optional[str]
    use_email: bool = False


class EmailReport(PackageSpecifier):
    """Model for a report using email"""

    rules_matched: list[str]
    recipient: Optional[str] = None
    inspector_url: Optional[str]
    additional_information: Optional[str]


# Taken from
# https://github.com/pypi/warehouse/blob/4d2628560e6e764dc80a026fa080e9cf70446c81/warehouse/observations/models.py#L109-L122
class ObservationKind(Enum):
    DependencyConfusion = "is_dependency_confusion"
    Malware = "is_malware"
    Spam = "is_spam"
    Other = "something_else"


class ObservationReport(BaseModel):
    """Model for a report using the PyPI Observation Api"""

    kind: ObservationKind
    summary: str
    inspector_url: Optional[str]
    extra: dict[str, Any] = Field(default_factory=dict)


class PackageScanResult(PackageSpecifier):
    """Client payload to server containing the results of a package scan"""

    commit: str
    score: int = 0
    inspector_url: Optional[str] = None
    rules_matched: list[str] = []
    distributions: Optional[Distributions] = None


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
