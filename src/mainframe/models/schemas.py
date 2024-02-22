from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ServerMetadata(BaseModel):
    """Server metadata"""

    server_commit: str
    rules_commit: str


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


class Subscription(BaseModel):
    """Represents a package name and an optional version."""

    package_name: str
    package_version: Optional[str] = None


class AddSubscription(Subscription):
    """Payload for when a user wants to subscribe to a malicious package."""

    discord_id: Optional[int] = None
    email_address: Optional[str] = None


class RemoveSubscription(Subscription):
    """Payload for when a user wants to unsubscribe from a malicious package."""

    user_id: UUID


class GetPerson(BaseModel):
    """Get a user's information and what packages they're subscribed to"""

    person_id: UUID
    discord_id: Optional[int] = None
    email_address: Optional[str] = None
    packages: list[str]
