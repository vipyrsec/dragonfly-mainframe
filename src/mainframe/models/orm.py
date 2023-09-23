# type: ignore

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from operator import or_
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Status(Enum):
    """
    Package status.

    QUEUED - Waiting to be sent to a worker
    PENDING - Waiting for a response from a worker
    FINISHED - Verdict received from worker
    FAILED - Something went wrong with the client when scanning this package
    """

    QUEUED = "queued"
    PENDING = "pending"
    FINISHED = "finished"
    FAILED = "failed"


package_rules = Table(
    "package_rules",
    Base.metadata,
    Column("scan_id", ForeignKey("scans.scan_id"), primary_key=True),
    Column("rule_id", ForeignKey("rules.id"), primary_key=True),
)


class Scan(Base):
    """The scans."""

    __tablename__: str = "scans"
    __table_args__ = (UniqueConstraint("name", "version"),)

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=FetchedValue(),
        default=uuid.uuid4,
    )

    name: Mapped[str]
    version: Mapped[str]
    status: Mapped[Status]

    score: Mapped[Optional[int]]
    inspector_url: Mapped[Optional[str]]
    rules: Mapped[list[Rule]] = relationship(secondary=package_rules)
    download_urls: Mapped[list[DownloadURL]] = relationship()

    queued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue(), default=lambda: datetime.now(timezone.utc)
    )
    queued_by: Mapped[str]

    pending_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pending_by: Mapped[Optional[str]]

    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_by: Mapped[Optional[str]]

    reported_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reported_by: Mapped[Optional[str]]

    fail_reason: Mapped[Optional[str]]

    commit_hash: Mapped[Optional[str]]


Index(None, Scan.status, postgresql_where=or_(Scan.status == Status.QUEUED, Scan.status == Status.PENDING))


class DownloadURL(Base):
    """Download URLs"""

    __tablename__: str = "download_urls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=FetchedValue(),
        default=uuid.uuid4,
    )

    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.scan_id"))

    url: Mapped[str]


class Rule(Base):
    """YARA rules"""

    __tablename__: str = "rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=FetchedValue(),
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(unique=True)
